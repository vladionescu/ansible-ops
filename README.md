Ansible Ops
===========

Run a playbook:

`ansible-playbook --ask-vault-pass -i hosts main.yml`

or

`ansible-playbook --vault-password-file /home/vlad/ops/vault_pass.txt -i /home/vlad/ops/ansible/hosts /home/vlad/ops/ansible/main.yml`


Edit encrypted vars: `ansible-vault edit vars/vault.yml`

Troubleshooting
---------------

If there's an error while mounting /data, then XFS needs to be checked.

mount: /mnt: mount(2) system call failed: Structure needs cleaning.

`xfs_repair /dev/disk/by-label/iscsi-data`
