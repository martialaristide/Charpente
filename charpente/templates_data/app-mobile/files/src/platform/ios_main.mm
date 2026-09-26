// iOS entry point (UIKit). Written without a Mac: adjust to your app's UI. See docs/apple.md.
#import <UIKit/UIKit.h>
#include <charpente/mobile.hpp>
#include "../engine/engine.hpp"

@interface AppDelegate : UIResponder <UIApplicationDelegate>
@property(strong, nonatomic) UIWindow *window;
@end

@implementation AppDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)launchOptions {
    @IDENT@::start();
    charpente::mobile::ios_notify(charpente::mobile::Event::Create);
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    self.window.rootViewController = [UIViewController new];
    [self.window makeKeyAndVisible];
    return YES;
}
- (void)applicationDidBecomeActive:(UIApplication *)application { charpente::mobile::ios_notify(charpente::mobile::Event::Resume); }
- (void)applicationWillResignActive:(UIApplication *)application { charpente::mobile::ios_notify(charpente::mobile::Event::Pause); }
- (void)applicationDidReceiveMemoryWarning:(UIApplication *)application { charpente::mobile::ios_notify(charpente::mobile::Event::LowMemory); }
@end

int main(int argc, char *argv[]) {
    @autoreleasepool { return UIApplicationMain(argc, argv, nil, NSStringFromClass([AppDelegate class])); }
}
