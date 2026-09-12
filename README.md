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

Apply the SSD migration and media settings without upgrading images (first run briefly restarts each migrated service, including Plex):

```sh
ansible-playbook --vault-password-file /home/vlad/ops/vault_pass.txt main.yml \
  --tags media_migrate,arr_settings -e downloaders_pull_images=false
```

- `arr_storage` recreates only Sonarr and Radarr as necessary, with a shared
  `/data:/data` mount. Existing download/media paths stay unchanged. A single
  mount allows hardlinks and atomic moves between download categories and
  libraries. These trusted importers can access the wider /data tree; individual
  application users and existing filesystem permissions remain in use.
- `arr_settings` reconciles settings through application APIs and removes the
  redundant Usenet-only Unpackerr container (its definition is retained). SABnzbd continues to unpack.
- The reconciler reads credentials from existing persistent application
  configurations using the Ansible-provided MEDIA_CONFIG_ROOT, discovers container IPs for management, and saves Docker DNS
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

SSD storage
-----------

Klaxon uses /srv/media-config/<service>/config on the system SSD for SABnzbd,
Sonarr, Radarr, Bazarr, Seerr, Prowlarr, Readarr, and Plex. The media_migrate tag
copies live config first, stops one service, performs a final sync, verifies
checksums, and switches its mount. Marker files prevent a redeploy from copying
stale HDD data over the active SSD configuration. Copy failure restarts the
original container and stops the deployment.

SAB's unfinished downloads live at /srv/media-downloads/incomplete-sab.
Completed downloads and media remain on /data, preserving atomic Arr imports.
Partial downloads are copied and verified with SAB stopped. One direct unpacker
is allowed because completed output still shares one HDD with Plex playback.
Existing cache size and network bandwidth limits are retained.

Original HDD configurations and partial-download directories are retained for
rollback; they are no longer current after cutover. Backups must now include
/srv/media-config. Do not simply remount the old copies after substantial use:
stop the service and sync its current SSD data back first, or restore a backup.

The targeted migration does not pull new images. A subsequent normal full
playbook retains its existing image-update behavior. To reconcile settings
manually after migration:

    sudo env MEDIA_CONFIG_ROOT=/srv/media-config /usr/local/sbin/reconcile-media
    sudo env MEDIA_CONFIG_ROOT=/srv/media-config /usr/local/sbin/reconcile-media --plex-only

Repeat media_migrate runs skip completed copies and should not restart
unchanged containers. For rollback, stop the affected service, sync its current
SSD config back to its original HDD path, reset media_config_root to
/data/docker, and redeploy it. To roll back SAB unfinished downloads, also
stop SAB, copy current partials back, reset download_dir in its stopped config
and media_incomplete_root, then redeploy. Do not delete migration markers
unless intentionally rebuilding a destination from an authoritative source.


Migration validation on 2026-09-12: all eight services use SSD configuration
mounts; Arr/Prowlarr database quick checks and health checks passed; Plex kept
its server identity and both libraries. A small 32 MiB direct-write/fsync
check measured about 277 MiB/s on SSD and 77 MiB/s on HDD with services running.
These are short concurrent-load samples, not sustained-download guarantees.
The initial Plex cutover exposed a missing task tag, now corrected; the
plex_cutover tag includes migration prerequisites and startup.

Use --check with the migration/settings tags to preview a repeat deployment.
Completed migration copies should be skipped and unchanged containers should
not be recreated. The Add host to correct group task may still report changed.
