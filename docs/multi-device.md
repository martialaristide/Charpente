# Deploying to every device at once

```bash
charpente deploy --device all                          # every connected Android device and emulator
charpente deploy --device all --logs                   # ... then follow all their logs in one stream
charpente deploy --device all --logs --log-filter MyApp --log-seconds 60
charpente deploy --device emulator-5554                # one device, as before
```

With `--device all` Charpente:

1. asks `adb` for every ready device (state `device`; `offline` and `unauthorized` ones are ignored) and reads each one's CPU ABIs (`getprop ro.product.cpu.abilist`);
2. picks, for each device, the first of its ABIs that Charpente can build (`arm64-v8a`, `armeabi-v7a`, `x86_64`); a device with none of them is **skipped and named** (`Skipped phone-2: runs mips ...`);
3. builds **one APK** with the native libraries for exactly the ABIs that are needed (no build per device, and an APK small enough to be worth installing);
4. installs and starts it on all devices **in parallel**. One device failing (no space, a refused install, a device that went away) is reported for that device (`FAILED emulator-5554: ...`) and **does not stop the others**;
5. exits 0 only if every device succeeded; 1 if any failed or none could be used (CH8009).

## One merged log

`--logs` starts `adb logcat` on every device that succeeded and prints one interleaved stream, each line tagged with its device:

```
[emulator-5554] 09-26 10:12:01.442 I/MyApp( 4711): started
[phone-1      ] 09-26 10:12:01.517 I/MyApp( 9032): started
```

Lines from one device stay in order, and lines from different devices never mix *inside* a line. `--log-filter TEXT` keeps only lines containing the text (case-insensitive); `--log-seconds N` stops after N seconds; otherwise
Ctrl+C stops it and the log processes are ended. With `--output jsonl`, every step is an event: `deploy.device_found`, `deploy.installing`, `deploy.launched`, `deploy.log` (device and line).

The same works for keys and signing as single-device deploys: `--keystore`/`--key-alias`, and the password comes from `CHARPENTE_KEYSTORE_PASSWORD`, never from the command line.

## Verified, and what is only simulated

* The APK really is built (real NDK, one APK for two ABIs) and the selection logic, parallel install, failure isolation, log merging and events are tested end to end.
* The *devices* in those tests are simulated by a small stand-in `adb` program. **A run of `--device all` against several real phones or emulators has not been done**; a single real emulator was used with the one-device path.
* HarmonyOS devices (`hdc`) and iOS are not covered by `--device all`.
