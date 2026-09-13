"""Document encryption and decryption service conforming to PLAN.md §12.6 C35, C36 (CMD-004)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import pikepdf

from pdftoolscli.backends.pikepdf_backend import PikepdfBackend
from pdftoolscli.domain.errors import ExitCode, PDFToolsError
from pdftoolscli.storage.atomic import AtomicPublisher
from pdftoolscli.storage.identity import assert_distinct_files
from pdftoolscli.storage.workspace import InvocationWorkspace


class EncryptionService:
    """Service providing PDF encryption (AES-256) and decryption."""

    def __init__(self, backend: PikepdfBackend | None = None) -> None:
        self.backend = backend or PikepdfBackend()

    def encrypt(
        self,
        input_path: Path,
        output_path: Path,
        owner_password: str,
        user_password: str | None = None,
        allow_empty_user: bool = False,
        print_permission: str = "full",
        modify_permission: str = "all",
        copy_permission: str = "allow",
        input_password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Encrypt a PDF document with AES-256 (Revision 6) and specified permissions."""
        assert_distinct_files(input_path, output_path, operation_name="encrypt")

        if not owner_password:
            raise PDFToolsError(
                "Owner password cannot be empty.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
                hint="Provide a non-empty owner password.",
            )

        effective_user = user_password or ""
        if not effective_user and not allow_empty_user:
            raise PDFToolsError(
                "User password is required when --allow-empty-user is not set.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
                hint="Provide a user password or explicitly pass --allow-empty-user.",
            )

        if effective_user and effective_user == owner_password:
            raise PDFToolsError(
                "Owner password and user password must be distinct.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
                hint="Use different secrets for the owner and user passwords.",
            )

        # Map print permission
        print_mode = print_permission.lower().strip()
        print_high = print_mode == "full"
        print_low = print_mode in ("full", "low")

        # Map modify permission
        mod_mode = modify_permission.lower().strip()
        mod_all = mod_mode == "all"
        mod_ann = mod_mode in ("all", "annotate")
        mod_form = mod_mode in ("all", "form")

        # Map copy permission
        copy_mode = copy_permission.lower().strip()
        allow_copy = copy_mode == "allow"

        perms = pikepdf.Permissions(
            accessibility=True,
            print_highres=print_high,
            print_lowres=print_low,
            extract=allow_copy,
            modify_annotation=mod_ann,
            modify_form=mod_form,
            modify_assembly=mod_all,
            modify_other=mod_all,
        )

        r_val: Literal[2, 3, 4, 5, 6] = 6
        enc = pikepdf.Encryption(
            owner=owner_password,
            user=effective_user,
            R=r_val,
            allow=perms,
        )

        with self.backend.open_document(input_path, password=input_password) as handle:
            page_count = len(handle.pdf.pages)

            with InvocationWorkspace() as ws:
                scratch = ws.create_scratch_file(prefix="encrypt-", suffix=".pdf")
                handle.pdf.save(scratch, encryption=enc)

                published = AtomicPublisher.publish_file(scratch, output_path, overwrite=overwrite)

        return {
            "command": "encrypt",
            "input": str(input_path.resolve()),
            "output": str(published.resolve()),
            "page_count": page_count,
            "algorithm": "AES-256",
            "permissions": {
                "print": print_mode,
                "modify": mod_mode,
                "copy": copy_mode,
                "accessibility": True,
            },
        }

    def decrypt(
        self,
        input_path: Path,
        output_path: Path,
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Remove encryption from a PDF document and publish unencrypted copy."""
        assert_distinct_files(input_path, output_path, operation_name="decrypt")

        with self.backend.open_document(input_path, password=password) as handle:
            if not handle.pdf.is_encrypted:
                raise PDFToolsError(
                    "The input PDF is not encrypted. Use a standard file copy instead.",
                    code="E_NOT_ENCRYPTED",
                    exit_code=ExitCode.USAGE_OR_SELECTION,
                    hint="Use a standard file copy instead.",
                )

            page_count = len(handle.pdf.pages)

            with InvocationWorkspace() as ws:
                scratch = ws.create_scratch_file(prefix="decrypt-", suffix=".pdf")
                # Saving without encryption argument removes encryption in pikepdf
                handle.pdf.save(scratch)

                published = AtomicPublisher.publish_file(scratch, output_path, overwrite=overwrite)

        return {
            "command": "decrypt",
            "input": str(input_path.resolve()),
            "output": str(published.resolve()),
            "page_count": page_count,
            "is_encrypted": False,
        }
