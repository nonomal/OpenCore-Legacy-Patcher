# Class for handling Storage Controller Patches, invocation from build.py
# Copyright (C) 2020-2022, Dhinak G, Mykola Grymalyuk

from resources import constants, device_probe, utilities
from resources.build import support
from data import model_array, smbios_data, cpu_data


class build_storage:

    def __init__(self, model, versions, config):
        self.model = model
        self.constants: constants.Constants = versions
        self.config = config
        self.computer = self.constants.computer


    def build(self):
        self.ahci_handling()
        self.pata_handling()
        self.misc_handling()
        self.pcie_handling()
        self.trim_handling()

    def ahci_handling(self):
        # MacBookAir6,x ship with an AHCI over PCIe SSD model 'APPLE SSD TS0128F' and 'APPLE SSD TS0256F'
        # This controller is not supported properly in macOS Ventura, instead populating itself as 'Media' with no partitions
        # To work-around this, use Monterey's AppleAHCI driver to force support
        if not self.constants.custom_model:
            sata_devices = [i for i in self.computer.storage if isinstance(i, device_probe.SATAController)]
            for controller in sata_devices:
                # https://linux-hardware.org/?id=pci:1179-010b-1b4b-9183
                if controller.vendor_id == 0x1179 and controller.device_id == 0x010b:
                    print("- Enabling AHCI SSD patch")
                    support.build_support(self.model, self.constants, self.config).enable_kext("MonteAHCIPort.kext", self.constants.monterey_ahci_version, self.constants.monterey_ahci_path)
                    break
        elif self.model in ["MacBookAir6,1", "MacBookAir6,2"]:
            print("- Enabling AHCI SSD patch")
            support.build_support(self.model, self.constants, self.config).enable_kext("MonteAHCIPort.kext", self.constants.monterey_ahci_version, self.constants.monterey_ahci_path)

        # ThirdPartyDrives Check
        if self.constants.allow_3rd_party_drives is True:
            for drive in ["SATA 2.5", "SATA 3.5", "mSATA"]:
                if not self.model in smbios_data.smbios_dictionary:
                    break
                if not "Stock Storage" in smbios_data.smbios_dictionary[self.model]:
                    break
                if drive in smbios_data.smbios_dictionary[self.model]["Stock Storage"]:
                    if not self.constants.custom_model:
                        if self.computer.third_party_sata_ssd is True:
                            print("- Adding SATA Hibernation Patch")
                            self.config["Kernel"]["Quirks"]["ThirdPartyDrives"] = True
                            break
                    else:
                        print("- Adding SATA Hibernation Patch")
                        self.config["Kernel"]["Quirks"]["ThirdPartyDrives"] = True
                        break


    def pata_handling(self):
        if not self.model in smbios_data.smbios_dictionary:
            return
        if not "Stock Storage" in smbios_data.smbios_dictionary[self.model]:
            return
        if not "PATA" in smbios_data.smbios_dictionary[self.model]["Stock Storage"]:
            return

        support.build_support(self.model, self.constants, self.config).enable_kext("AppleIntelPIIXATA.kext", self.constants.piixata_version, self.constants.piixata_path)


    def pcie_handling(self):
        if not self.constants.custom_model and (self.constants.allow_oc_everywhere is True or self.model in model_array.MacPro):
            # Use Innie's same logic:
            # https://github.com/cdf/Innie/blob/v1.3.0/Innie/Innie.cpp#L90-L97
            for i, controller in enumerate(self.computer.storage):
                print(f"- Fixing PCIe Storage Controller ({i + 1}) reporting")
                if controller.pci_path:
                    self.config["DeviceProperties"]["Add"][controller.pci_path] = {"built-in": 1}
                else:
                    print(f"- Failed to find Device path for PCIe Storage Controller {i}, falling back to Innie")
                    support.build_support(self.model, self.constants, self.config).enable_kext("Innie.kext", self.constants.innie_version, self.constants.innie_path)

        if not self.constants.custom_model and self.constants.allow_nvme_fixing is True:
            nvme_devices = [i for i in self.computer.storage if isinstance(i, device_probe.NVMeController)]
            for i, controller in enumerate(nvme_devices):
                print(f"- Found 3rd Party NVMe SSD ({i + 1}): {utilities.friendly_hex(controller.vendor_id)}:{utilities.friendly_hex(controller.device_id)}")
                self.config["#Revision"][f"Hardware-NVMe-{i}"] = f"{utilities.friendly_hex(controller.vendor_id)}:{utilities.friendly_hex(controller.device_id)}"

                # Disable Bit 0 (L0s), enable Bit 1 (L1)
                nvme_aspm = (controller.aspm & (~0b11)) | 0b10

                if controller.pci_path:
                    print(f"- Found NVMe ({i}) at {controller.pci_path}")
                    self.config["DeviceProperties"]["Add"].setdefault(controller.pci_path, {})["pci-aspm-default"] = nvme_aspm
                    self.config["DeviceProperties"]["Add"][controller.pci_path.rpartition("/")[0]] = {"pci-aspm-default": nvme_aspm}
                else:
                    if "-nvmefaspm" not in self.config["NVRAM"]["Add"]["7C436110-AB2A-4BBB-A880-FE41995C9F82"]["boot-args"]:
                        print("- Falling back to -nvmefaspm")
                        self.config["NVRAM"]["Add"]["7C436110-AB2A-4BBB-A880-FE41995C9F82"]["boot-args"] += " -nvmefaspm"

                if (controller.vendor_id != 0x144D and controller.device_id != 0xA804):
                    # Avoid injecting NVMeFix when a native Apple NVMe drive is present
                    # https://github.com/acidanthera/NVMeFix/blob/1.0.9/NVMeFix/NVMeFix.cpp#L220-L225
                    support.build_support(self.model, self.constants, self.config).enable_kext("NVMeFix.kext", self.constants.nvmefix_version, self.constants.nvmefix_path)

        # Apple RAID Card check
        if not self.constants.custom_model:
            if self.computer.storage:
                for storage_controller in self.computer.storage:
                    if storage_controller.vendor_id == 0x106b and storage_controller.device_id == 0x008A:
                        # AppleRAIDCard.kext only supports pci106b,8a
                        support.build_support(self.model, self.constants, self.config).enable_kext("AppleRAIDCard.kext", self.constants.apple_raid_version, self.constants.apple_raid_path)
                        break
        elif self.model.startswith("Xserve"):
            # For Xserves, assume RAID is present
            # Namely due to Xserve2,1 being limited to 10.7, thus no hardware detection
            support.build_support(self.model, self.constants, self.config).enable_kext("AppleRAIDCard.kext", self.constants.apple_raid_version, self.constants.apple_raid_path)


    def misc_handling(self):
        if not self.model in smbios_data.smbios_dictionary:
            return
        if not "CPU Generation" in smbios_data.smbios_dictionary[self.model]:
            return

        # With macOS Monterey, Apple's SDXC driver requires the system to support VT-D
        # However pre-Ivy Bridge don't support this feature
        if smbios_data.smbios_dictionary[self.model]["CPU Generation"] <= cpu_data.cpu_data.sandy_bridge.value:
            if (self.constants.computer.sdxc_controller and not self.constants.custom_model) or (self.model.startswith("MacBookPro8") or self.model.startswith("Macmini5")):
                support.build_support(self.model, self.constants, self.config).enable_kext("BigSurSDXC.kext", self.constants.bigsursdxc_version, self.constants.bigsursdxc_path)


    def trim_handling(self):
        if self.constants.apfs_trim_timeout is False:
            print(f"- Disabling APFS TRIM timeout")
            self.config["Kernel"]["Quirks"]["SetApfsTrimTimeout"] = 0