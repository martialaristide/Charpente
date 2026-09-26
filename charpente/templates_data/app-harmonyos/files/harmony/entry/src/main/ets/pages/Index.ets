import entry from 'libentry.so';

@Entry
@Component
struct Index {
  @State message: string = 'Tap me: native add(2, 3)';

  build() {
    Row() {
      Column() {
        Text(this.message)
          .fontSize(28)
          .fontWeight(FontWeight.Bold)
          .onClick(() => {
            this.message = 'add(2, 3) = ' + entry.add(2, 3);   // runs in C++ (src/napi_entry.cpp)
          })
      }
      .width('100%')
    }
    .height('100%')
  }
}
