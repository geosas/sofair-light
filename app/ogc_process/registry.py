"""Registry of the host's OGC processes, injected into the reusable engine
``flask_ogc_api_processes`` (via ``create_ogc_blueprint``).

The engine (external package) knows NONE of these processes: they are passed to it
at blueprint construction. Each class follows the package contract
(``metadata`` / ``Schema`` / ``OutputSchema`` / ``run`` / ``get_metadata``).

The demo process ``buffer`` (Example_OGC_Process) is deliberately NOT
registered here: only the 5 SOFAIR business processes are exposed.
"""

from app.ogc_process.config_create_datastream import ConfigCreateDatastream
from app.ogc_process.config_post_to_sta import ConfigPostToSTA
from app.ogc_process.data_driver_inspect_before_sta import DataDriverInspectBeforeSTA
from app.ogc_process.data_driver_post_to_sta import DataDriverPostToSTA
from app.ogc_process.get_data_infos import GetDataInfos

HOST_PROCESSES = [
    ConfigCreateDatastream,
    ConfigPostToSTA,
    DataDriverInspectBeforeSTA,
    DataDriverPostToSTA,
    GetDataInfos,
]
