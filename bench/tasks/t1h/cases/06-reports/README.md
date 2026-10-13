# Sensor report aggregation

Pure Python service; put src on the import path. Inputs follow these contracts. Review supported behavior violations without editing.

loading.rows drops only None readings, retaining zero. units.to_celsius converts F with (F-32)*5/9, leaves C unchanged, rejects other units. aggregating.mean returns None on empty input, otherwise arithmetic mean; count is length. exporting.report converts each reading once then rounds to 2 decimals with Python round. Labels strip spaces. Row order is stable.
