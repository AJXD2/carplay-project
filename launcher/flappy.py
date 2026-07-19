#!/usr/bin/env python3
import pygame, random, sys

W, H = 800, 480
pygame.init()
pygame.display.set_caption("flappy")
screen = pygame.display.set_mode((W, H), pygame.NOFRAME)
pygame.mouse.set_visible(False)
clock = pygame.time.Clock()
font = pygame.font.SysFont("dejavusans", 36, bold=True)
small = pygame.font.SysFont("dejavusans", 22)

BIRD_X = 140
BIRD_R = 16
GAP = 150
PIPE_W = 70
GRAVITY = 0.45
FLAP = -8.5
PIPE_SPEED = 3.4
PIPE_EVERY = 90

def new_game():
    return {
        "bird_y": H / 2,
        "vel": 0.0,
        "pipes": [],  # each: {x, gap_y}
        "frame": 0,
        "score": 0,
        "dead": False,
    }

state = new_game()

def spawn_pipe():
    gap_y = random.randint(80, H - 80 - GAP)
    state["pipes"].append({"x": W, "gap_y": gap_y, "scored": False})

running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
            if state["dead"]:
                state = new_game()
            else:
                state["vel"] = FLAP
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False
            elif event.key == pygame.K_SPACE:
                if state["dead"]:
                    state = new_game()
                else:
                    state["vel"] = FLAP

    if not state["dead"]:
        state["frame"] += 1
        state["vel"] += GRAVITY
        state["bird_y"] += state["vel"]

        if state["frame"] % PIPE_EVERY == 0:
            spawn_pipe()

        for p in state["pipes"]:
            p["x"] -= PIPE_SPEED
            if not p["scored"] and p["x"] + PIPE_W < BIRD_X:
                p["scored"] = True
                state["score"] += 1
        state["pipes"] = [p for p in state["pipes"] if p["x"] > -PIPE_W]

        if state["bird_y"] < 0 or state["bird_y"] > H:
            state["dead"] = True
        for p in state["pipes"]:
            if p["x"] < BIRD_X + BIRD_R and p["x"] + PIPE_W > BIRD_X - BIRD_R:
                if state["bird_y"] - BIRD_R < p["gap_y"] or state["bird_y"] + BIRD_R > p["gap_y"] + GAP:
                    state["dead"] = True

    screen.fill((30, 30, 46))
    for p in state["pipes"]:
        pygame.draw.rect(screen, (58, 107, 122), (p["x"], 0, PIPE_W, p["gap_y"]))
        pygame.draw.rect(screen, (58, 107, 122), (p["x"], p["gap_y"] + GAP, PIPE_W, H - (p["gap_y"] + GAP)))

    pygame.draw.circle(screen, (242, 169, 59), (BIRD_X, int(state["bird_y"])), BIRD_R)

    score_surf = font.render(str(state["score"]), True, (255, 255, 255))
    screen.blit(score_surf, (W / 2 - score_surf.get_width() / 2, 20))

    if state["dead"]:
        msg = font.render("Tap to restart", True, (255, 255, 255))
        screen.blit(msg, (W / 2 - msg.get_width() / 2, H / 2 - 20))

    hint = small.render("tap / click to flap, esc to quit", True, (150, 150, 150))
    screen.blit(hint, (10, H - 30))

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
sys.exit()
