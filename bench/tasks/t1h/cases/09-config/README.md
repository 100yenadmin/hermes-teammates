# Configuration overlay

Pure Python service; put src on the import path. Review supported behavior violations without editing.

overlays.merge replaces top-level keys shallowly, including explicit None. resolving.build merges then validates integer port 1..65535 (bool rejected) and bool enabled. parsing.port rejects bool and uses default only for absent port. False enabled is valid. Empty override keeps defaults; validation returns same object; strings invalid ports; unknown keys preserved.
