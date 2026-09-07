"""Process registry for the standalone / demo application.

**This is the single place to register the processes served in standalone mode.**
``create_app()`` injects ``EXAMPLE_PROCESSES`` into the engine automatically, so
adding a process is two lines here: import its class, then add it to the list.

Each process lives in its own module (see ``Example_OGC_Process.py``,
``hello_world.py``); this file only assembles them.
"""
from .Example_OGC_Process import BufferProcess
from .hello_world import HelloWorldProcess

# One entry per process. The engine keys them by ``metadata["id"]``.
EXAMPLE_PROCESSES = [
    BufferProcess,
    HelloWorldProcess,
]
