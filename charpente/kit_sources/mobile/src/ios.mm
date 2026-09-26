// charpente-mobile on iOS / visionOS: NSLog, the Documents directory, resources from the app bundle.
// Written without a Mac: not compiled or run by Charpente's tests (see docs/apple.md).
#include <charpente/mobile.hpp>

#import <Foundation/Foundation.h>

namespace charpente {
namespace mobile {

namespace detail {
void write_log(LogLevel level, const char *tag, const char *line) {
    static const char *const names[] = {"D", "I", "W", "E"};
    NSLog(@"%s/%s: %s", names[static_cast<int>(level)], tag, line);
}
}  // namespace detail

const char *platform_name() { return "ios"; }

void ios_notify(Event event) { dispatch(event); }

std::string data_dir() {
    NSArray<NSString *> *dirs = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES);
    return dirs.count > 0 ? std::string([dirs[0] UTF8String]) : std::string();
}

bool read_asset(const char *path, std::vector<unsigned char> &out) {
    NSString *relative = [NSString stringWithUTF8String:path];
    NSString *full = [[NSBundle mainBundle] pathForResource:[relative stringByDeletingPathExtension]
                                                     ofType:[relative pathExtension]];
    NSData *data = full != nil ? [NSData dataWithContentsOfFile:full] : nil;
    if (data == nil) return false;
    const unsigned char *bytes = static_cast<const unsigned char *>(data.bytes);
    out.assign(bytes, bytes + data.length);
    return true;
}

}  // namespace mobile
}  // namespace charpente
