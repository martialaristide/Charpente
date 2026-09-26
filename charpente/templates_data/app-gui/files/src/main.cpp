// A small ImGui application. `@NAME@ --frames 60` exits after 60 frames (handy for smoke tests and CI).
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include <GLFW/glfw3.h>
#include "imgui.h"
#include "imgui_impl_glfw.h"
#include "imgui_impl_opengl3.h"

int main(int argc, char** argv) {
    long max_frames = 0;                         // 0 = run until the window is closed
    for (int i = 1; i + 1 < argc; ++i) {
        if (std::strcmp(argv[i], "--frames") == 0) max_frames = std::atol(argv[i + 1]);
    }

    if (!glfwInit()) { std::fprintf(stderr, "glfwInit failed\n"); return 1; }
    GLFWwindow* window = glfwCreateWindow(800, 480, "@TITLE@", nullptr, nullptr);
    if (!window) { std::fprintf(stderr, "could not create a window (is there a display?)\n"); glfwTerminate(); return 2; }
    glfwMakeContextCurrent(window);
    glfwSwapInterval(1);

    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGui_ImplGlfw_InitForOpenGL(window, true);
    ImGui_ImplOpenGL3_Init("#version 130");

    float slider = 0.5f;
    bool checked = true;
    int clicks = 0;
    long frame = 0;
    while (!glfwWindowShouldClose(window) && (max_frames == 0 || frame < max_frames)) {
        glfwPollEvents();
        ImGui_ImplOpenGL3_NewFrame();
        ImGui_ImplGlfw_NewFrame();
        ImGui::NewFrame();

        ImGui::Begin("@TITLE@");
        ImGui::Text("Frame %ld, %.1f FPS", frame, ImGui::GetIO().Framerate);
        ImGui::SliderFloat("Slider", &slider, 0.0f, 1.0f);
        ImGui::Checkbox("Checkbox", &checked);
        if (ImGui::Button("Click me")) ++clicks;
        ImGui::Text("Clicked %d times", clicks);
        ImGui::End();

        ImGui::Render();
        int w, h;
        glfwGetFramebufferSize(window, &w, &h);
        glViewport(0, 0, w, h);
        glClearColor(0.10f, 0.12f, 0.16f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
        ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());
        glfwSwapBuffers(window);
        ++frame;
    }

    ImGui_ImplOpenGL3_Shutdown();
    ImGui_ImplGlfw_Shutdown();
    ImGui::DestroyContext();
    glfwDestroyWindow(window);
    glfwTerminate();
    std::printf("rendered %ld frames\n", frame);
    return 0;
}
