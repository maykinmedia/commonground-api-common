from django.apps import apps as global_apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import override_settings

import pytest
from zgw_consumers.constants import APITypes, AuthTypes


class BaseMigrationTest:
    app = None
    migrate_from = None  # The migration before the one we want to test
    migrate_to = None  # The migration we want to test
    setting_overrides = {}

    @pytest.fixture(autouse=True)
    def setup_migration(self, db):
        """
        Setup the migration test by reversing to `migrate_from` state,
        then applying the `migrate_to` state.
        """
        assert self.app is not None, "You must define the `app` attribute"
        assert self.migrate_from is not None, "You must define `migrate_from`"
        assert self.migrate_to is not None, "You must define `migrate_to`"

        # Step 1: Set up the MigrationExecutor
        executor = MigrationExecutor(connection)

        # Step 2: Reverse to the starting migration state
        migrate_from = [(self.app, self.migrate_from)]
        migrate_to = [(self.app, self.migrate_to)]
        old_migrate_state = executor.migrate(migrate_from)
        old_apps = old_migrate_state.apps

        # Step 3: Run the `setup_before_migration` hook with old state models
        self.setup_before_migration(old_apps)

        # Step 4: Apply the migration we want to test with any settings overrides
        with override_settings(**self.setting_overrides):
            executor = MigrationExecutor(connection)
            executor.loader.build_graph()  # reload the graph in case of dependency changes
            executor.migrate(migrate_to)

        # Set `self.apps` to the post-migration state
        self.apps = executor.loader.project_state(migrate_to).apps

    def setup_before_migration(self, apps):
        """
        Hook to set up the state before the migration. Subclasses can
        override this to create data or perform other setup actions.
        """
        pass


class TestMigrateAPICredentialToService(BaseMigrationTest):
    app = "vng_api_common"
    migrate_from = "0005_auto_20190614_1346"
    migrate_to = "0006_delete_apicredential"

    def setup_before_migration(self, apps):
        Service = apps.get_model("zgw_consumers", "Service")
        APICredential = apps.get_model("vng_api_common", "APICredential")

        APICredential.objects.create(
            api_root="https://example.com/zaken/api/v1/",
            label="Zaken API",
            client_id="user",
            secret="secret",
            user_id="user",
            user_representation="User",
        )

        APICredential.objects.create(
            api_root="https://example.com/api/v1/",
            label="Selectielijst API",
            client_id="user2",
            secret="secret2",
            user_id="user2",
            user_representation="User2",
        )

        APICredential.objects.create(
            api_root="https://example.com/documenten/api/v1/",
            label="Documenten API",
            client_id="user3",
            secret="secret3",
            user_id="user3",
            user_representation="User3",
        )
        Service.objects.create(
            api_root="https://example.com/documenten/api/v1/",
            label="Documenten",
            slug="already-exists",
            api_type=APITypes.drc,
            auth_type=AuthTypes.zgw,
            client_id="user4",
            secret="secret4",
            user_id="user4",
            user_representation="User4",
        )

    def test_migrate_api_credentials_to_services(self):
        Service = global_apps.get_model("zgw_consumers", "Service")

        zaken_service = Service.objects.get(slug="zaken-api")

        assert zaken_service.api_root == "https://example.com/zaken/api/v1/"
        assert zaken_service.label == "Zaken API"
        assert zaken_service.api_type == APITypes.zrc
        assert zaken_service.auth_type == AuthTypes.zgw
        assert zaken_service.client_id == "user"
        assert zaken_service.secret == "secret"
        assert zaken_service.user_id == "user"
        assert zaken_service.user_representation == "User"

        selectielijst_service = Service.objects.get(slug="selectielijst-api")

        assert selectielijst_service.api_root == "https://example.com/api/v1/"
        assert selectielijst_service.label == "Selectielijst API"
        assert selectielijst_service.api_type == APITypes.orc
        assert selectielijst_service.auth_type == AuthTypes.zgw
        assert selectielijst_service.client_id == "user2"
        assert selectielijst_service.secret == "secret2"
        assert selectielijst_service.user_id == "user2"
        assert selectielijst_service.user_representation == "User2"

        documenten_service = Service.objects.get(slug="already-exists")

        # Because there already was a service for this API root, that data is used instead
        assert documenten_service.api_root == "https://example.com/documenten/api/v1/"
        assert documenten_service.label == "Documenten"
        assert documenten_service.api_type == APITypes.drc
        assert documenten_service.auth_type == AuthTypes.zgw
        assert documenten_service.client_id == "user4"
        assert documenten_service.secret == "secret4"
        assert documenten_service.user_id == "user4"
        assert documenten_service.user_representation == "User4"


class TestMigrateAuthorizationsConfigAPIRootToService(BaseMigrationTest):
    app = "authorizations"
    migrate_from = "0015_auto_20220318_1608"
    migrate_to = "0016_remove_authorizationsconfig_api_root_and_more"

    def setup_before_migration(self, apps):
        Service = apps.get_model("zgw_consumers", "Service")
        AuthorizationsConfig = apps.get_model("authorizations", "AuthorizationsConfig")

        config, _ = AuthorizationsConfig.objects.get_or_create()
        config.api_root = "https://example.com/autorisaties/api/v1/"
        config.save()

        self.service = Service.objects.create(
            api_root="https://example.com/autorisaties/api/v1/",
            label="Autorisaties",
            slug="autorisaties",
            api_type=APITypes.ac,
            auth_type=AuthTypes.zgw,
            client_id="user",
            secret="secret",
            user_id="user",
            user_representation="User",
        )

    def test_migrate_api_root_to_service(self):
        AuthorizationsConfig = global_apps.get_model(
            "authorizations", "AuthorizationsConfig"
        )

        config, _ = AuthorizationsConfig.objects.get_or_create()

        assert config.authorizations_api_service.pk == self.service.pk
        assert (
            config.authorizations_api_service.api_root
            == "https://example.com/autorisaties/api/v1/"
        )