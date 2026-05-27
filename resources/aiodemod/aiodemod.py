import random
import asyncio

from jeedomdaemon.base_daemon import BaseDaemon
from jeedomdaemon.base_config import BaseConfig

class DemoConfig(BaseConfig):
    """This is where you declare your custom argument/configuration

    Remember that all usual arguments are managed by the BaseConfig class already so you only have to take care of yours; e.g. user & password in this case
    """
    def __init__(self):
        super().__init__()

        self.add_argument("--user", type=str, default='Harrison')
        self.add_argument("--password", type=str)

class AIODemod(BaseDaemon):
    """This is the main class of you daemon"""

    def __init__(self) -> None:
        # Standard initialisation
        super().__init__(config=DemoConfig(), on_start_cb=self.on_start, on_message_cb=self.on_message, on_stop_cb=self.on_stop)

        # Below you can init your own variables if needed
        self._search_task = None


    async def on_start(self):
        """
        This method will be called when your daemon start.
        This is the place where you should create yours tasks, login to remote system, etc
        """
        # create your own background tasks if needed.
        # `_search_task` is here to demo usage of background task in a daemon
        self._search_task = asyncio.create_task(self._search_animals())

        # maybe we have to use some values received from Jeedom via argument?
        # we declared user & password in our DemoConfig so we can use them directly
        await self._login_somewhere(self._config.user, self._config.password)

    async def _login_somewhere(self, user, password):
        await asyncio.sleep(2)
        self._logger.debug("Login done with '%s'", user)

    async def on_message(self, message: list):
        """
        This function will be called once a message is received from Jeedom; check on api key is done already, just care about your logic
        You must implement the different actions that your daemon can handle.
        """
        if message['action'] == 'think':
            await self._think(message['message'])
        elif message['action'] == 'ping':
            for i in range(1, 4):
                await self.send_to_jeedom({'pingpong':f'ping {i}'})
                await asyncio.sleep(2)
                await self.send_to_jeedom({'pingpong':f'pong {i}'})
                await asyncio.sleep(2)
        else:
            self._logger.warning('Unknown action: %s', message['action'])

    async def _think(self, message):
        # this is a demo implementation of a single function, this function will be invoked once the corresponding call is received from Jeedom
        random_int = random.randint(3, 15)
        self._logger.info("==> think on received '%s' during %is", message, random_int)
        await self.send_to_jeedom({'alert':f"Let me think about '{message}' during {random_int}s"})
        await asyncio.sleep(random_int)
        self._logger.info("==> '%s' was an interesting information, thanks for the nap", message)
        await self.send_to_jeedom({'alert':f"'{message}' was an interesting information, thanks for the nap"})

    async def _search_animals(self):
        # this is a demo implementation of a backgroudn task, you must have a try ... except asyncio.CancelledError: ... that will intercept the cancel request from the loop
        self._logger.info("Start searching animals")

        animals = {
            0: 'Cat',
            1: 'Dog',
            2: 'Duck',
            3: 'Sheep',
            4: 'Horse',
            5: 'Cow',
            6: 'Goat',
            7: 'Rabbit'
        }

        try:
            max_int = len(animals) - 1
            while True:
                animal = animals[random.randint(0, max_int)]
                nbr = random.randint(0, 97)
                self._logger.info("I found %i %s(s)", nbr, animal.lower())
                await self.add_change(animal, nbr)
                await asyncio.sleep(random.randint(0, 2))
        except asyncio.CancelledError:
            self._logger.info("Stop searching animals")

    async def on_stop(self):
        """
        This callback will be called when daemon need to stop`
        You need to close your remote connexions and cancel background tasks if any here.
        """
        self._search_task.cancel()


AIODemod().run()