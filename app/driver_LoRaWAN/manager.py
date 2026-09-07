import re
import os
import importlib
import sys

from app.config import Config


class ScriptManagerLoRaWAN:
    scripts = []
    dir_name = 'driver_LoRaWAN'
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
    def run_script(cls, script_name, *args, **kwargs):
        """
        Run the 'run' function of the module identified by script_name.
        """

        # Check that the driver exists by scanning the driver directory.
        # Do not use cls.scripts because it may be empty after application startup.
        if script_name in cls.get_scripts_name():
            # importlib.import_module(module_name) does not reload the module
            # if it is already imported
            module_name = f"app.{cls.dir_name}.driver.{script_name}"
            module = importlib.import_module(module_name)
            return module.run(*args, **kwargs)
        else:
            raise ValueError(f"The script '{script_name}' does not exist.")

    @classmethod
    def refresh(cls):
        """
        Reload all LoRaWAN drivers to apply code changes without restarting.
        """
        result = []
        for script in cls.get_scripts_name():
            module_name = f"app.{cls.dir_name}.driver.{script}"
            try:
                if module_name in sys.modules:
                    importlib.reload(sys.modules[module_name])
                else:
                    importlib.import_module(module_name)
                result.append({"driver": script})
            except Exception as e:
                result.append({"driver": script, "error": str(e)})
        return result

    @classmethod
    def get_metadata(cls):
        """Retrieve the script's metadata to generate documentation."""
        cls.script = cls.get_scripts_name()
        functions_metadata = []
        identifiers = {}
        examples = {}
        for script in cls.script:
            print(script)
            try:
                module_name = f"app.{cls.dir_name}.driver.{script}"
                if module_name in sys.modules:
                    print(f"🔄 Reloading module {module_name}")
                    module = importlib.reload(sys.modules[module_name])
                else:
                    module = importlib.import_module(module_name)
                docstring = module.run.__doc__
                identifier = module.get_identifier()
                identifiers[script] = identifier
                examples[script] = getattr(module, "EXAMPLE_PAYLOAD", "")
            except Exception as e:
                print(e)
                functions_metadata.append({"driver": script,
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
                functions_metadata.append(doc)
            except Exception as e:
                print(e)
                functions_metadata.append({"driver": script,
                                           "description": "Unable to load the documentation",
                                           "Args": "", "Returns": "", "error": True})
        return functions_metadata, identifiers, examples
