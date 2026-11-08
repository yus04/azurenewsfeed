import os
import unittest
from unittest.mock import MagicMock, patch

from scripts import upload_to_blob


class GetContainerClientTests(unittest.TestCase):
    @patch.dict(
        os.environ,
        {
            "AZURE_STORAGE_ACCOUNT_NAME": "testaccount",
            "AZURE_STORAGE_CONTAINER": "raw-articles",
        },
    )
    @patch("scripts.upload_to_blob.AzureCliCredential")
    @patch("scripts.upload_to_blob.BlobServiceClient")
    def test_uses_azure_cli_credential_without_creating_container(
        self, blob_service_client, credential
    ):
        container_client = MagicMock()
        service_client = blob_service_client.return_value
        service_client.get_container_client.return_value = container_client

        result = upload_to_blob.get_container_client()

        credential_instance = credential.return_value
        blob_service_client.assert_called_once_with(
            account_url="https://testaccount.blob.core.windows.net",
            credential=credential_instance,
        )
        service_client.get_container_client.assert_called_once_with("raw-articles")
        container_client.create_container.assert_not_called()
        self.assertIs(result, container_client)

    @patch.dict(os.environ, {}, clear=True)
    def test_requires_storage_account_name(self):
        with self.assertRaisesRegex(
            RuntimeError, "AZURE_STORAGE_ACCOUNT_NAME environment variable is not set"
        ):
            upload_to_blob.get_container_client()


if __name__ == "__main__":
    unittest.main()
