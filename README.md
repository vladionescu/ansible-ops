Ansible Ops
===========

Run a playbook:

`ansible-playbook --ask-vault-pass main.yml`

or

`ansible-playbook --vault-password-file /home/vlad/ops/vault_pass.txt /home/vlad/ops/ansible/main.yml`


Edit encrypted vars: `ansible-vault edit vars/vault.yml`

Troubleshooting
---------------

If there's an error while mounting /data, then XFS needs to be checked.

mount: /mnt: mount(2) system call failed: Structure needs cleaning.

`xfs_repair /dev/disk/by-label/iscsi-data`

Media stack maintenance (klaxon)
-------------------------------

Klaxon opts into `downloaders_optimizations_enabled` in `main.yml`.
Cactus retains its existing container layout and settings.

Apply the media changes without upgrading images or restarting Plex:

```sh
ansible-playbook --vault-password-file /home/vlad/ops/vault_pass.txt main.yml \
  --tags arr_storage,arr_settings -e downloaders_pull_images=false
```

- `arr_storage` recreates only Sonarr and Radarr as necessary, with a shared
  `/data:/data` mount. Existing download/media paths stay unchanged. A single
  mount allows hardlinks and atomic moves between download categories and
  libraries. These trusted importers can access the wider /data tree; individual
  application users and existing filesystem permissions remain in use.
- `arr_settings` reconciles settings through application APIs and stops the
  redundant Usenet-only Unpackerr container. SABnzbd continues to unpack.
- The reconciler reads credentials from existing persistent application
  configurations, discovers container IPs for management, and saves Docker DNS
  names for inter-service connections. No credentials are stored in Git.
- Changes are backed up under `/data/docker/connection-backups/<timestamp>/`,
  readable only by root. API failures are reported without printing secrets.
- Prowlarr uses internal URLs for Sonarr, Radarr, and Readarr. Sonarr/Radarr
  managed indexers are tested before legacy unmanaged Radarr entries are
  disabled. Legacy entries are retained, not deleted.
- Sonarr profile 1 is `Standard TV (1080p)`: SD/720p fallbacks remain available,
  upgrades stop at WEB 1080p or better, and 4K/remux downloads are not selected
  by this profile. Anime custom-format scores are zeroed in non-anime profiles.
  Dedicated quality choices (including Ultra-HD) otherwise remain unchanged.
  The dedicated Anime profile and all custom-format definitions are retained.
- Seerr's default non-4K Sonarr service uses profile 1. Its recently-added Plex
  scan runs every two minutes. Sonarr's browser-local Add Series preferences
  are not controlled by this playbook; choose Standard TV there when needed.
- Plex intro/credits analysis runs in its existing maintenance window
  (currently 02:00–05:00). This preference is applied live, without restarting
  Plex. Existing skip markers remain usable.
- No library files are renamed, moved, deleted, searched for, or downloaded by
  the settings reconciler. Profile changes affect future release selection.

Verification performed: live indexer tests, empty health reports for
Sonarr/Radarr, and hardlink plus inode-preserving rename tests between each
download category and its library, executed as each app's own UID/GID.
A second reconciler run should report `"changed": false`.

Rollback: disable the opt-in to return to the former container mounts and
Unpackerr provisioning, then restore any desired application settings via their
APIs using the root-only backups. Turning off the opt-in alone intentionally
does not overwrite persistent app settings. Restore the former Seerr/Plex
preferences explicitly if desired.

Deferred: SSD migration of application databases/Plex metadata, SSD download
staging, and benchmark-based SAB cache/unpack tuning. Plex metadata migration
requires a separate stop/copy/start maintenance window. No such migration is
performed by these tags.
