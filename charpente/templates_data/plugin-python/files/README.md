# @TITLE@

```
charpente pkg install
charpente build
python test_@IDENT@.py
```

The module is built with the Python that runs Charpente (its headers, and on Windows its import library): build with the interpreter you
will import it from. To ship wheels, build once per Python version and platform.
