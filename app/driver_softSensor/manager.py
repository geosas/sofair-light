"""
Need to change like the lorawan manager
"""
import os
import importlib
import sys

from app.config import Config


class ScriptManagerSoftSensor:
    dir_name = 'driver_softSensor'
    directory = os.path.join(Config.BASEDIR, dir_name, 'driver')

    @classmethod
    def get_scripts_name(cls):
        """
        Scan the 'driver' folder and import all Python modules
        when the app start
        """

        return [
            filename[:-3]
            for filename in os.listdir(cls.directory)
            if filename.endswith('.py') and not filename.startswith('__')
        ]

    @classmethod
    def load(cls, script_name):
        """Import (with hot-reload) and return the method module, without running it."""
        if script_name not in cls.get_scripts_name():
            raise ValueError(
                f"The soft-sensor method '{script_name}' does not exist.")
        module_name = f"app.{cls.dir_name}.driver.{script_name}"
        if module_name in sys.modules:
            return importlib.reload(sys.modules[module_name])
        return importlib.import_module(module_name)

    @classmethod
    def run_script(cls, script_name, *args, **kwargs):
        """Run the `run` function of the method identified by script_name."""
        return cls.load(script_name).run(*args, **kwargs)

    @classmethod
    def get_metadata(cls):
        """Retrieve the script's metadata to generate documentation."""
        methods = []
        for script in cls.get_scripts_name():
            try:
                module = cls.load(script)
                meta = dict(getattr(module, 'METADATA', {}))
                meta.setdefault('id', script)
                meta.setdefault('label', script)
                meta.setdefault(
                    'description', (module.run.__doc__ or '').strip())
                meta.setdefault('params', [])
                methods.append(meta)
            except Exception as e:
                methods.append({"id": script, "label": script,
                                "description": f"Unable to load the method: {e}",
                                "params": [], "error": True})
        return methods
