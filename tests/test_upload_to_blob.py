import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from scripts import upload_to_blob


class UploadBehaviorTests(unittest.TestCase):
    def test_lists_existing_blobs_and_skips_duplicate_article_ids(self):
        container_client = MagicMock()
        container_client.list_blobs.return_value = [
            SimpleNamespace(name="raw/articles/2026/11/08/existing.json")
        ]
        new_blob_client = MagicMock()
        container_client.get_blob_client.return_value = new_blob_client
        articles = [
            {
                "id": "existing",
                "collectedAt": "2026-11-08T00:00:00+00:00",
            },
            {
                "id": "new",
                "collectedAt": "2026-11-08T00:00:00+00:00",
            },
        ]

        with patch.object(
            upload_to_blob,
            "_recent_month_prefixes",
            return_value=["raw/articles/2026/11/"],
        ):
            result = upload_to_blob.upload_articles(container_client, articles)

        self.assertEqual(result, (1, 1, []))
        container_client.list_blobs.assert_called_once_with(
            name_starts_with="raw/articles/2026/11/"
        )
        container_client.get_blob_client.assert_called_once_with(
            "raw/articles/2026/11/08/new.json"
        )
        new_blob_client.upload_blob.assert_called_once()

    @patch(
        "scripts.upload_to_blob.upload_articles",
        return_value=(0, 0, [("blob.json", "denied")]),
    )
    @patch("scripts.upload_to_blob.get_container_client")
    @patch(
        "scripts.upload_to_blob.load_staged_articles",
        return_value=[{"link": "https://example.com"}],
    )
    def test_main_exits_nonzero_when_upload_fails(
        self, _load_articles, _get_container, _upload_articles
    ):
        with self.assertRaises(SystemExit) as raised:
            upload_to_blob.main()

        self.assertEqual(raised.exception.code, 1)


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
