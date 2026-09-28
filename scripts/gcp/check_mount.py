"""Exercise disk bootstrap guards with fake devices; never mount/format a disk."""
from pathlib import Path
import os
import shlex
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "infra/gcp/templates/startup.sh.tftpl").read_text()
function = source.split("mount_data_disk() {", 1)[1].split("\nmount_data_disk /", 1)[0]
function = "mount_data_disk() {" + function
mocks = r'''
function [() {
  if [[ $# == 3 && "$1" == -b ]]; then return 0; fi
  builtin [ "$@"
}
formatted=0
mounted=0
[[ "$CASE" == mounted || "$CASE" == wrong_mount ]] && mounted=1
blkid() {
  if [[ "$1" != -s ]]; then
    [[ "$CASE" != blank && "$CASE" != unknown ]] || [[ $formatted == 1 ]]
  elif [[ "$2" == TYPE ]]; then
    if [[ "$CASE" == wrong_fs ]]; then printf 'xfs\n'; else printf 'ext4\n'; fi
  else printf 'expected-uuid\n'; fi
}
wipefs() { if [[ "$CASE" == unknown ]]; then printf 'unrecognized-signature\n'; fi; }
cmp() { [[ "$CASE" != unknown ]]; }
mkfs.ext4() { formatted=1; printf 'format\n' >>"$EVENTS"; }
mountpoint() { [[ $mounted == 1 ]]; }
mount() { mounted=1; printf 'mount\n' >>"$EVENTS"; }
findmnt() { if [[ "$CASE" == wrong_mount ]]; then printf 'other-uuid\n'; else printf 'expected-uuid\n'; fi; }
chown() { printf 'owner\n' >>"$EVENTS"; }
chmod() { printf 'permissions\n' >>"$EVENTS"; }
'''
for case in ("blank", "existing", "mounted", "unknown", "wrong_fs", "wrong_mount", "nonempty", "fstab_conflict", "symlink"):
    with tempfile.TemporaryDirectory(prefix="trading-mount-test-") as tmp:
        temp = Path(tmp)
        target, events, fstab = temp / "mount", temp / "events", temp / "fstab"
        target.mkdir()
        if case == "nonempty":
            (target / "existing-data").write_text("must not hide")
        if case == "symlink":
            target = temp / "symlink"
            target.symlink_to(temp / "mount", target_is_directory=True)
        fstab.write_text(f"UUID=other-uuid {target} ext4 defaults,nodev,nosuid 0 2\n" if case == "fstab_conflict" else "")
        script = "set -euo pipefail\n" + mocks + "\n" + function.replace("/etc/fstab", shlex.quote(str(fstab)))
        script += "\nmount_data_disk /dev/FAKE_ONLY " + shlex.quote(str(target)) + "\n"
        result = subprocess.run(["bash"], input=script, text=True, capture_output=True,
                                env={**os.environ, "CASE": case, "EVENTS": str(events)})
        calls = events.read_text().splitlines() if events.exists() else []
        success = case in ("blank", "existing", "mounted")
        assert (result.returncode == 0) == success, (case, result.stderr)
        assert ("format" in calls) == (case == "blank"), (case, calls)
        if success:
            assert "owner" in calls and "permissions" in calls, (case, calls)
            assert ("mount" in calls) == (case != "mounted"), (case, calls)
        else:
            assert not calls, (case, calls)
print("9 dedicated-disk bootstrap scenarios passed with fake devices")
