# @TITLE@

```
charpente toolchain install emsdk               # once (git + python; downloads about 1.5 GB)
charpente build --platform wasm32-emscripten
charpente run --platform wasm32-emscripten      # runs the .js under Node
```

For the browser, copy `web/index.html` next to `build/Debug-wasm32-emscripten/@NAME@/@NAME@.js` and `.wasm`, and serve the folder over
HTTP (`python -m http.server`): browsers do not load `.wasm` from `file://`.
