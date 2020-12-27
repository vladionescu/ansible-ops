Ansible Ops
===========

Run a playbook:

`ansible-playbook --ask-vault-pass -i hosts main.yml`

or

`ansible-playbook --vault-password-file /home/vlad/ops/vault_pass.txt -i /home/vlad/ops/ansible/hosts /home/vlad/ops/ansible/main.yml`


Edit encrypted vars: `ansible-vault edit vars/vault.yml`
