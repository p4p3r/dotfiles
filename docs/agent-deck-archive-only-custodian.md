# Archive-only custodian companion

This Linux tool copies exactly one explicitly named existing regular file. It
does not delete, move, overwrite, or change the source, and it does not inspect
Agent Deck state. It creates no service or timer. Home Manager installs the
manual command only when `programs.agent-deck-archive-only-custodian.enable = true`.

The source, archive root, and restore root must be absolute, normalized paths
without symlinks. Ancestors must be owned by the caller or root and cannot be
group or world writable, apart from root-owned sticky directories such as
`/tmp`. The source must belong to the caller, have exactly one link, be a
regular file with no group or other permissions, and be at most 1 MiB. The
archive and restore roots must already exist, belong to the caller, and be mode
`0700`. A label and restore destination are single safe path components.

```sh
agent-deck-archive-only-custodian archive \
  --source /tmp/private-source/item \
  --archive-root /tmp/private-archive \
  --label rehearsal-1

agent-deck-archive-only-custodian restore \
  --archive-root /tmp/private-archive \
  --label rehearsal-1 \
  --destination-root /tmp/private-restore \
  --destination item-restored
```

Archive publication creates a new private label directory containing `content`
and `manifest.json`. The versioned manifest contains only a SHA-256 digest,
byte count, mode, and numeric owner ID; it contains no artifact path or body.
The tool checks source identity and metadata throughout the read, syncs both
files and their directory, and publishes the label atomically without replacing
an existing label. Interrupted private `.pending-*` staging directories are
left for inspection and are never treated as published archives.

Restore checks the manifest and archived content before writing. It verifies
digest, size, owner, mode, and stable file identity, then atomically publishes
one new destination file. Existing destinations are never replaced. A failed
write may leave a private `.restore-pending-*` file for inspection, but cannot
publish an incomplete destination. Successful restores remain in place.
Output is one bounded JSON status and code, without paths or content. A failure
must be investigated before claiming a completed archive or restore.
