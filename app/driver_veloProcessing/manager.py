import re
import os
import importlib
import sys

from app.config import Config


class ScriptManagerVeloProcessing:
    scripts = []
    dir_name = 'driver_veloProcessing'
    directory = os.path.join(Config.BASEDIR, dir_name, 'driver')

    @classmethod
    def get_scripts_name(cls):
        """
        Scan the 'driver' folder and import all Python modules.
        """
        return [
            filename[:-3]
            for filename in os.listdir(cls.directory)
            if filename.endswith('.py') and not filename.startswith('__')
        ]

    @classmethod
    def load(cls, script_name):
        """Import (with hot-reload) and return the driver module, without running it.

        Lets the route layer access driver functions other than
        `run` (e.g. `authenticate`, `ALLOWED_EXTENSIONS`).
        """
        if script_name not in cls.get_scripts_name():
            raise ValueError(f"The script '{script_name}' does not exist.")
        module_name = f"app.{cls.dir_name}.driver.{script_name}"
        if module_name in sys.modules:
            print(f"🔄 Reloading module {module_name}")
            return importlib.reload(sys.modules[module_name])
        return importlib.import_module(module_name)

    @classmethod
    def run_script(cls, script_name, *args, **kwargs):
        """
        Run the 'run' function of the module identified by script_name.
        """
        return cls.load(script_name).run(*args, **kwargs)

    @classmethod
    def refresh(cls):
        """Hot-reload every driver module.
        """
        result = []
        for script in cls.get_scripts_name():
            try:
                cls.load(script)
                result.append({"driver": script})
            except Exception as e:
                result.append({"driver": script, "error": str(e)})
        return result

    @classmethod
    def get_metadata(cls):
        """Retrieve the scripts' metadata to generate documentation."""
        # cls.get_scripts_name()
        functions_metadata = []
        idp = 0
        for script in cls.get_scripts_name():
            idp += 1
            try:
                module_name = f"app.{cls.dir_name}.driver.{script}"
                if module_name in sys.modules:
                    print(f"🔄 Reloading module {module_name}")
                    module = importlib.reload(sys.modules[module_name])
                else:
                    module = importlib.import_module(module_name)
                docstring = module.run.__doc__

            except Exception as e:
                print(e)
                functions_metadata.append({"id": idp,
                                           "driver": script,
                                           "description": f"Unable to load the driver: <br>{str(e)}",
                                           "Args": "", "Returns": "", "error": True})
                continue
            try:
                print(2)
                doc = {"driver": script}
                match = re.split(r"\n\s*(Args|Returns)\s*:", docstring)
                doc["description"] = match[0].strip().replace(
                    "\n", "<br>") if match else docstring.strip()

                for i in ["Args", "Returns"]:
                    match = re.search(
                        rf"{i}\s*:(.*?)(\n\s*[A-Z][a-zA-Z]*\s*:|\Z)", docstring, re.DOTALL)
                    doc[i] = match.group(1).strip().replace(
                        "\n", "<br>") if match else ""
                doc['id'] = idp
                functions_metadata.append(doc)
            except Exception as e:
                print(e)
                functions_metadata.append({"id": idp,
                                           "driver": script,
                                           "description": "Unable to load the documentation",
                                           "Args": "", "Returns": "", "error": True})
        return functions_metadata
