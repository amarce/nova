#!/usr/bin/env python
"""Apply OVS port migration fix to nova/compute/manager.py"""
import sys
import os

target = '/usr/local/lib/python2.7/dist-packages/nova/compute/manager.py'
if not os.path.exists(target):
    print("ERROR: %s not found" % target)
    sys.exit(1)

with open(target, 'r') as f:
    content = f.read()

# Check if already patched
if '_wait_for_ports_active' in content:
    print("Already patched, nothing to do.")
    sys.exit(0)

# --- Patch 1: Add the method after check_can_live_migrate_source ---
marker1 = "        LOG.debug('source check data is %s', result)\n        return result\n"
method = '''        LOG.debug('source check data is %s', result)
        return result

    # Begin clouding patch: wait for OVS ports to become ACTIVE during live migration
    def _wait_for_ports_active(self, context, instance, network_info):
        """Wait for Neutron ports to become ACTIVE on destination.

        During live migration, the OVS port on the destination may
        not be ready when the VM is transferred. This method polls
        Neutron for port status before proceeding.
        """
        if not utils.is_neutron():
            return

        timeout = CONF.vif_plugging_timeout
        if not timeout:
            return

        port_ids = [vif['id'] for vif in network_info if vif['id']]
        if not port_ids:
            return

        LOG.debug('Waiting for ports to become ACTIVE: %s',
                  port_ids, instance=instance)

        poll_interval = 1
        elapsed = 0
        while elapsed < timeout:
            all_active = True
            for port_id in port_ids:
                try:
                    port_data = self.network_api.show_port(
                        context, port_id)
                    status = port_data['port'].get('status')
                    if status != 'ACTIVE':
                        all_active = False
                        LOG.debug('Port %(p)s is %(s)s',
                                  {'p': port_id, 's': status},
                                  instance=instance)
                        break
                except Exception:
                    LOG.warning(_LW('Failed to query port '
                                    '%(port)s status'),
                                {'port': port_id},
                                instance=instance)
                    all_active = False
                    break

            if all_active:
                LOG.debug('All ports ACTIVE on destination',
                          instance=instance)
                return

            greenthread.sleep(poll_interval)
            elapsed += poll_interval

        LOG.warning(_LW('Timed out waiting for ports ACTIVE'),
                    instance=instance)
    # End clouding patch
'''

if marker1 not in content:
    print("ERROR: Could not find insertion point for method.")
    sys.exit(1)

content = content.replace(marker1, method, 1)

# --- Patch 2: Add the call in pre_live_migration ---
marker2 = "        self.driver.ensure_filtering_rules_for_instance(instance,\n                                            network_info)\n"
call = '''        self.driver.ensure_filtering_rules_for_instance(instance,
                                            network_info)

        # Begin clouding patch: call port wait before pre_live_migration completes
        # Wait for Neutron ports to become ACTIVE on destination
        # before proceeding, preventing network timeouts.
        self._wait_for_ports_active(context, instance, network_info)
        # End clouding patch
'''

if marker2 not in content:
    print("ERROR: Could not find insertion point for call site.")
    sys.exit(1)

content = content.replace(marker2, call, 1)

# Write backup and patched file
backup = target + '.bak'
import shutil
shutil.copy2(target, backup)
print("Backup saved to %s" % backup)

with open(target, 'w') as f:
    f.write(content)

print("Patch applied successfully!")
