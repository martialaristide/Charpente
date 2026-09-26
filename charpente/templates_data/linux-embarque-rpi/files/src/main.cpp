// Reads the CPU temperature the way Linux boards expose it, once per second.
#include <chrono>
#include <cstdio>
#include <fstream>
#include <thread>

static double cpu_temperature_celsius() {
    std::ifstream file("/sys/class/thermal/thermal_zone0/temp");
    long milli = 0;
    if (!(file >> milli)) return -1.0;
    return static_cast<double>(milli) / 1000.0;
}

int main() {
    for (int i = 0; i < 5; ++i) {
        const double t = cpu_temperature_celsius();
        if (t < 0) std::printf("no thermal sensor here (is this a board?)\n");
        else std::printf("CPU %.1f C\n", t);
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
    return 0;
}
