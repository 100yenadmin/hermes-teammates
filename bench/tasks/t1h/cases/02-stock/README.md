# Stock reservations

Pure Python service; use src on the import path. Inputs obey the domains below unless a rejection rule is stated. Public entry points compose the named helpers. Review concrete observable violations of this contract. Do not edit files.

stock.available subtracts held quantities once. reserve.place requires positive quantity and admits exact remaining capacity. release.cancel releases only the named reservation and repeating cancellation is a no-op. orders.fulfil removes the held quantity once from on_hand and removes its hold. Empty orders sum to zero; IDs are case-sensitive; a missing cancellation is a no-op; inventory snapshots are copies.
