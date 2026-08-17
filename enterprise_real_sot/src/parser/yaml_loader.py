import os
import yaml
import logging

logger = logging.getLogger("NetBoxImporter")

class IntentLoaderError(Exception):
    """Base exception for all Intent Loader errors."""
    pass

class YamlLoadError(IntentLoaderError):
    """Raised when a YAML file fails to load or parse."""
    pass

class MissingGlobalConfigError(IntentLoaderError):
    """Raised when the global configuration file is missing."""
    pass

class MissingDeviceMetadataError(IntentLoaderError):
    """Raised when a device folder is missing the mandatory device.yaml file."""
    pass

class DeviceSiteNotFoundError(IntentLoaderError):
    """Raised when a site configuration file cannot be found."""
    pass

class YamlLoader:
    def __init__(self, base_intent_dir):
        """
        Initialize the Loader with the path to the intent/ directory.
        """
        self.base_intent_dir = os.path.abspath(base_intent_dir)
        self.global_dir = os.path.join(self.base_intent_dir, "global")
        self.sites_dir = os.path.join(self.base_intent_dir, "sites")
        self.devices_dir = os.path.join(self.base_intent_dir, "devices")

    def load_yaml(self, filepath, required=False):
        """
        Safely load a single YAML file.
        If required is True, raises appropriate custom exceptions on failure.
        """
        if not os.path.exists(filepath):
            if required:
                raise YamlLoadError(f"Required YAML file not found: {filepath}")
            logger.debug(f"Optional YAML file not found: {filepath}")
            return {}
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data if data is not None else {}
        except yaml.YAMLError as e:
            raise YamlLoadError(f"YAML Syntax Error in file {filepath}: {e}")
        except Exception as e:
            raise YamlLoadError(f"Failed to read file {filepath}: {e}")

    def discover_devices(self):
        """
        Scans intent/devices/ to automatically discover all device names.
        Any folder containing a 'device.yaml' file is considered a device.
        Returns a dictionary mapping device_name to its folder path.
        """
        devices = {}
        if not os.path.exists(self.devices_dir):
            logger.error(f"Devices directory not found: {self.devices_dir}")
            return devices

        for root, dirs, files in os.walk(self.devices_dir):
            if "device.yaml" in files:
                device_name = os.path.basename(root)
                devices[device_name] = root
                logger.info(f"Discovered device '{device_name}' at path: {root}")
        return devices

    def load_global(self):
        """
        Loads the global configuration file.
        """
        global_path = os.path.join(self.global_dir, "global.yaml")
        if not os.path.exists(global_path):
            raise MissingGlobalConfigError(f"Mandatory global config not found at: {global_path}")
        return self.load_yaml(global_path, required=True)

    def load_site(self, site_slug):
        """
        Loads a site-specific site.yaml configuration.
        """
        site_file_path = os.path.join(self.sites_dir, site_slug, "site.yaml")
        if not os.path.exists(site_file_path):
            # Fallback to direct search (e.g. intent/sites/hyderabad.yaml)
            site_file_path = os.path.join(self.sites_dir, f"{site_slug}.yaml")
            
        if not os.path.exists(site_file_path):
            raise DeviceSiteNotFoundError(
                f"Mandatory site configuration for site '{site_slug}' not found at expected path: {site_file_path}"
            )
        return self.load_yaml(site_file_path, required=True)

    def load_device(self, device_name, device_path):
        """
        Dynamically loads all YAML/YML files inside the device directory.
        Required: device.yaml must exist.
        """
        device_data = {}
        device_meta_path = os.path.join(device_path, "device.yaml")
        if not os.path.exists(device_meta_path):
            raise MissingDeviceMetadataError(f"Device '{device_name}' is missing mandatory device.yaml.")

        # Read all files in the directory
        for filename in os.listdir(device_path):
            if filename.endswith((".yaml", ".yml")):
                key = os.path.splitext(filename)[0]
                filepath = os.path.join(device_path, filename)
                # Load the file
                content = self.load_yaml(filepath, required=(filename == "device.yaml"))
                
                if filename == "device.yaml":
                    # Merge all top-level keys of device.yaml directly into device_data
                    if isinstance(content, dict):
                        device_data.update(content)
                else:
                    # For other files (like interfaces.yaml), use the single-key unpacking logic
                    if isinstance(content, dict) and len(content) == 1 and key in content:
                        device_data[key] = content[key]
                    else:
                        device_data[key] = content

        return device_data

    def load_all(self):
        """
        Orchestrates the entire load phase.
        1. Loads the global config.
        2. Discovers all devices.
        3. Loads site and local device files for each discovered device.
        Returns a dictionary containing raw configurations for each device.
        """
        result = {}

        # 1. Load global configuration
        global_config = self.load_global()

        # 2. Discover devices
        devices = self.discover_devices()

        # 3. Load site and device configurations
        for device_name, device_path in devices.items():
            # Load the device specific details first to get the site slug
            device_raw = self.load_device(device_name, device_path)
            
            # Extract site slug from the flat or nested device dict
            site_slug = device_raw.get("device", {}).get("site")
            if not site_slug:
                raise MissingDeviceMetadataError(
                    f"Device '{device_name}' does not specify a site slug in device.yaml"
                )

            # Load site config
            site_config = self.load_site(site_slug)

            result[device_name] = {
                "global": global_config,
                "site": site_config,
                "device": device_raw
            }

        return result

