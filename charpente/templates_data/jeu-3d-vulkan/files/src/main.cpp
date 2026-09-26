// Vulkan bootstrap: loads the loader dynamically with volk, creates an instance with the extensions GLFW needs, lists the
// GPUs and their queue families. From here: a surface, a device, a swapchain, a render pass and your first triangle.
#include <cstdio>
#include <vector>

#include <volk.h>
#include <GLFW/glfw3.h>

int main() {
    if (volkInitialize() != VK_SUCCESS) { std::fprintf(stderr, "no Vulkan loader found (install a GPU driver / the Vulkan runtime)\n"); return 2; }
    if (!glfwInit()) { std::fprintf(stderr, "glfwInit failed\n"); return 1; }
    if (!glfwVulkanSupported()) { std::fprintf(stderr, "GLFW: Vulkan is not supported here\n"); glfwTerminate(); return 2; }

    uint32_t extension_count = 0;
    const char** extensions = glfwGetRequiredInstanceExtensions(&extension_count);

    VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};
    app.pApplicationName = "@NAME@";
    app.apiVersion = VK_API_VERSION_1_1;
    VkInstanceCreateInfo info{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    info.pApplicationInfo = &app;
    info.enabledExtensionCount = extension_count;
    info.ppEnabledExtensionNames = extensions;
    VkInstance instance = VK_NULL_HANDLE;
    if (vkCreateInstance(&info, nullptr, &instance) != VK_SUCCESS) { std::fprintf(stderr, "vkCreateInstance failed\n"); return 3; }
    volkLoadInstance(instance);

    uint32_t gpu_count = 0;
    vkEnumeratePhysicalDevices(instance, &gpu_count, nullptr);
    std::vector<VkPhysicalDevice> gpus(gpu_count);
    vkEnumeratePhysicalDevices(instance, &gpu_count, gpus.data());
    std::printf("%u Vulkan device(s):\n", gpu_count);
    for (VkPhysicalDevice gpu : gpus) {
        VkPhysicalDeviceProperties props;
        vkGetPhysicalDeviceProperties(gpu, &props);
        std::printf("  %s (API %u.%u.%u)\n", props.deviceName, VK_VERSION_MAJOR(props.apiVersion),
                    VK_VERSION_MINOR(props.apiVersion), VK_VERSION_PATCH(props.apiVersion));
        uint32_t families = 0;
        vkGetPhysicalDeviceQueueFamilyProperties(gpu, &families, nullptr);
        std::vector<VkQueueFamilyProperties> queues(families);
        vkGetPhysicalDeviceQueueFamilyProperties(gpu, &families, queues.data());
        for (uint32_t i = 0; i < families; ++i) {
            std::printf("    queue family %u: %u queue(s)%s%s\n", i, queues[i].queueCount,
                        (queues[i].queueFlags & VK_QUEUE_GRAPHICS_BIT) ? " graphics" : "",
                        (queues[i].queueFlags & VK_QUEUE_COMPUTE_BIT) ? " compute" : "");
        }
    }
    vkDestroyInstance(instance, nullptr);
    glfwTerminate();
    return 0;
}
