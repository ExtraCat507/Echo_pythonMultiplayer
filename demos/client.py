import copy
import logging
import asyncio
import threading
import time
from collections import deque
from dataclasses import asdict
from typing import Dict
import zmq
from zmq.asyncio import Context, Socket
import arcade
from pymunk.vec2d import Vec2d

from movement import KeysPressed, MOVE_MAP, apply_movement
from dataclasses import PlayerEvent, PlayerState, GameState

logger = logging.getLogger(__name__)
logger.setLevel('INFO')
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600

RECT_WIDTH = 50
RECT_HEIGHT = 50

MOVEMENT_SPEED = 10
UPDATE_TICK = 30

class Rectangle:
    def __init__(self, x, y, color, filled=True):
        self.position = Vec2d(x, y)
        self.color = color
        self.filled = filled

    def draw(self):
        if self.filled:
            arcade.draw_rect_filled( arcade.types.rect.Rect.from_kwargs(x=self.position.x, y=self.position.y, width=50, height=50), self.color)
        else:
            arcade.draw_rect_outline(arcade.XYWH(self.position.x, self.position.y, 50, 50), self.color, border_width=4)

class MyGame(arcade.Window):
    def __init__(self, width, height):
        super().__init__(width, height, title="Multiplayer Demo")
        arcade.set_background_color(arcade.color.GRAY)

        self.player = Rectangle(0, 0, arcade.color.GREEN_YELLOW, filled=False)
        self.player_position_snapshot = copy.copy(self.player.position)

        self.ghost = Rectangle(0, 0, arcade.color.BLACK)

        self.player_input = PlayerEvent()
        self.game_state = GameState(player_states=[PlayerState()],game_seconds=0)
        self.position_buffer = deque(maxlen=2)
        self.time_since_state_update = 0

    def on_update(self,dt):
        # Now calculate the new position based on the server information
        if len(self.position_buffer) < 2:
            return

        # These are the last two positions. p1 is the latest, p0 is the
        # one immediately preceding it.
        p0, t0 = self.position_buffer[0]
        p1, t1 = self.position_buffer[1]

        dtt = t1 - t0
        if dtt == 0:
            return

        # Calculate a PREDICTED future position, based on these two.
        velocity = (p1 - p0) / dtt

        # predicted position
        predicted_position = velocity * dtt + p1

        x = (self.time_since_state_update - 0) / dtt
        x = min(x, 1)
        interp_position = self.player_position_snapshot.interpolate_to(predicted_position, x)

        self.player.position = interp_position
        #self.player.position = p1
        self.ghost.position = p1

        self.time_since_state_update += dt

    def on_draw(self):
        #arcade.start_render()
        self.clear()
        #self.ghost.draw()
        self.player.draw()

    def on_key_press(self, key, modifiers):
        self.player_input.keys[key] = True

    def on_key_release(self, key, modifiers):
        self.player_input.keys[key] = False


async def iomain(window: MyGame, loop):
    ctx = Context()

    sub_sock: Socket = ctx.socket(zmq.SUB)
    sub_sock.connect('tcp://localhost:25000')
    sub_sock.subscribe('')  # Required for PUB+SUB

    push_sock: Socket = ctx.socket(zmq.PUSH)
    push_sock.connect('tcp://localhost:25001')

    async def send_player_input():
        """ Task A """
        while True:
            d = asdict(window.player_input)
            msg = dict(event=d)
            await push_sock.send_json(msg)
            await asyncio.sleep(1 / UPDATE_TICK)

    async def receive_game_state():
        """ Task B """
        while True:
            gs_string = await sub_sock.recv_string()
            window.game_state.from_json(gs_string)
            ps = window.game_state.player_states[0]
            window.position_buffer.append( (Vec2d(ps.x, ps.y), time.time()) )
            window.time_since_state_update = 0
            window.player_position_snapshot = copy.copy(window.player.position)

    try:
        await asyncio.gather(send_player_input(), receive_game_state())
    finally:
        sub_sock.close(1)
        push_sock.close(1)
        ctx.destroy(linger=1)

def thread_worker(window: MyGame):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(iomain(window, loop))
    loop.run_forever()

def main():
    window = MyGame(SCREEN_WIDTH, SCREEN_HEIGHT)
    thread = threading.Thread(
        target=thread_worker, args=(window,), daemon=True)
    thread.start()
    arcade.run()

if __name__ == "__main__":
    main()
