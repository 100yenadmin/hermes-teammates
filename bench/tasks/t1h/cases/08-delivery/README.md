# Async delivery

Pure Python service; put src on the import path. Review supported behavior violations without editing.

transport.send awaits client.send returning {ok: bool}. delivery.submit awaits transport and returns that boolean; OSError becomes False; ValueError propagates. deadlines.wait takes milliseconds, rejects negative timeouts; expired includes exact deadline. results.status maps only True to sent. Text preserves case; destination strips spaces; coroutine construction defers execution.
