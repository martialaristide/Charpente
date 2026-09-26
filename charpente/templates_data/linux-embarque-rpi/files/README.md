# @TITLE@

Cross-compiled for 64-bit ARM Linux. Once (no admin rights, nothing added to PATH):

```
charpente toolchain install zig
charpente build --platform linux-arm64 --config Release
```

Copy `build/Release-linux-arm64/@NAME@/@NAME@` to the board (`scp`) and run it there. `charpente run` will not run it on your
machine (CH8004): it is built for another CPU.
