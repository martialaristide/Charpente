#include "breakout.hpp"

#include <algorithm>
#include <cmath>

namespace @IDENT@ {

Game new_game() {
    Game game;
    for (int row = 0; row < 4; ++row) {
        for (int col = 0; col < 8; ++col) {
            game.bricks.push_back({0.1f + 0.114f * static_cast<float>(col), 0.85f - 0.05f * static_cast<float>(row), 0.1f, 0.035f});
        }
    }
    return game;
}

static bool overlaps(const Rect& r, float cx, float cy, float radius) {
    return std::fabs(cx - r.x) <= r.w / 2 + radius && std::fabs(cy - r.y) <= r.h / 2 + radius;
}

void step(Game& g, float dt, int move) {
    if (g.won() || g.lost()) return;
    g.paddle.x = std::clamp(g.paddle.x + static_cast<float>(move) * 0.9f * dt, g.paddle.w / 2, 1.0f - g.paddle.w / 2);
    g.ball_x += g.ball_dx * dt;
    g.ball_y += g.ball_dy * dt;
    if (g.ball_x < g.ball_r) { g.ball_x = g.ball_r; g.ball_dx = std::fabs(g.ball_dx); }
    if (g.ball_x > 1 - g.ball_r) { g.ball_x = 1 - g.ball_r; g.ball_dx = -std::fabs(g.ball_dx); }
    if (g.ball_y > 1 - g.ball_r) { g.ball_y = 1 - g.ball_r; g.ball_dy = -std::fabs(g.ball_dy); }
    if (g.ball_dy < 0 && overlaps(g.paddle, g.ball_x, g.ball_y, g.ball_r)) {
        g.ball_dy = std::fabs(g.ball_dy);
        g.ball_dx += (g.ball_x - g.paddle.x) * 1.5f;              // steer with the point of impact
    }
    for (auto it = g.bricks.begin(); it != g.bricks.end(); ++it) {
        if (overlaps(*it, g.ball_x, g.ball_y, g.ball_r)) {
            g.bricks.erase(it);
            g.ball_dy = -g.ball_dy;
            g.score += 10;
            break;
        }
    }
    if (g.ball_y < -g.ball_r) {                                  // missed: lose a life, serve again
        --g.lives;
        g.ball_x = g.paddle.x;
        g.ball_y = 0.2f;
        g.ball_dx = 0.35f;
        g.ball_dy = 0.5f;
    }
}

}  // namespace @IDENT@
