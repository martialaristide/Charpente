#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"

#define BLINK_GPIO 2          /* the on-board LED of most ESP32 dev boards */
static const char *TAG = "@IDENT@";

void app_main(void) {
    gpio_reset_pin(BLINK_GPIO);
    gpio_set_direction(BLINK_GPIO, GPIO_MODE_OUTPUT);
    int level = 0;
    for (;;) {
        gpio_set_level(BLINK_GPIO, level);
        ESP_LOGI(TAG, "LED %s", level ? "on" : "off");
        level = !level;
        vTaskDelay(pdMS_TO_TICKS(500));
    }
}
