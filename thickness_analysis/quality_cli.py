"""Shared command-line options for thickness-fit quality selection."""

from __future__ import annotations

import argparse
import math

from .volume import QualityCuts


def add_quality_cut_arguments(
    parser: argparse.ArgumentParser,
    *,
    include_minimum_contrast: bool = True,
    include_maximum_width: bool = True,
) -> None:
    parser.add_argument("--minimum-theta-deg", type=float, help="minimum folded endpoint theta [0,90 degrees]")
    parser.add_argument("--maximum-theta-deg", type=float, help="maximum folded endpoint theta [0,90 degrees]")
    if include_minimum_contrast:
        parser.add_argument(
            "--minimum-contrast", type=float, help="minimum fitted profile contrast"
        )
    parser.add_argument(
        "--minimum-fit-r2", type=float, help="minimum accepted fit R²"
    )
    parser.add_argument(
        "--maximum-fit-nrmse", type=float, help="maximum accepted fit NRMSE"
    )
    parser.add_argument(
        "--maximum-reduced-chi2",
        type=float,
        help="maximum accepted reduced χ²",
    )
    parser.add_argument(
        "--minimum-fit-p-value",
        type=float,
        help="minimum accepted χ² goodness-of-fit p-value",
    )
    parser.add_argument(
        "--maximum-width-error-nm",
        type=float,
        help="maximum accepted propagated width uncertainty [nm]",
    )
    parser.add_argument(
        "--maximum-width-relative-error",
        type=float,
        help="maximum accepted width_error / width",
    )
    if include_maximum_width:
        parser.add_argument(
            "--maximum-width-nm",
            type=float,
            help="optional legacy width cut; disabled by default",
        )


def quality_cuts_from_args(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> QualityCuts:
    cuts = QualityCuts(
        minimum_theta_deg=getattr(args, "minimum_theta_deg", None),
        maximum_theta_deg=getattr(args, "maximum_theta_deg", None),
        minimum_contrast=getattr(args, "minimum_contrast", None),
        minimum_fit_r2=getattr(args, "minimum_fit_r2", None),
        maximum_fit_nrmse=getattr(args, "maximum_fit_nrmse", None),
        maximum_reduced_chi2=getattr(args, "maximum_reduced_chi2", None),
        minimum_fit_p_value=getattr(args, "minimum_fit_p_value", None),
        maximum_width_error_nm=getattr(args, "maximum_width_error_nm", None),
        maximum_width_relative_error=getattr(
            args, "maximum_width_relative_error", None
        ),
        maximum_width_nm=getattr(args, "maximum_width_nm", None),
    )
    for value in (cuts.minimum_theta_deg, cuts.maximum_theta_deg):
        if value is not None and (not math.isfinite(value) or not 0 <= value <= 90):
            parser.error("theta limits must be finite and between 0 and 90 degrees")
    if (cuts.minimum_theta_deg is not None and cuts.maximum_theta_deg is not None
            and cuts.minimum_theta_deg > cuts.maximum_theta_deg):
        parser.error("minimum theta cannot exceed maximum theta")
    nonnegative = {
        "--minimum-contrast": cuts.minimum_contrast,
        "--maximum-fit-nrmse": cuts.maximum_fit_nrmse,
        "--maximum-reduced-chi2": cuts.maximum_reduced_chi2,
        "--maximum-width-error-nm": cuts.maximum_width_error_nm,
        "--maximum-width-relative-error": cuts.maximum_width_relative_error,
        "--maximum-width-nm": cuts.maximum_width_nm,
    }
    for name, value in nonnegative.items():
        if value is not None and value < 0.0:
            parser.error(f"{name} must be non-negative")
    if cuts.minimum_fit_r2 is not None and cuts.minimum_fit_r2 > 1.0:
        parser.error("--minimum-fit-r2 cannot exceed 1")
    if cuts.minimum_fit_p_value is not None and not (
        0.0 <= cuts.minimum_fit_p_value <= 1.0
    ):
        parser.error("--minimum-fit-p-value must be between 0 and 1")
    return cuts


def quality_cut_cli_tokens(cuts: QualityCuts) -> list[str]:
    names = {
        "minimum_theta_deg": "--minimum-theta-deg",
        "maximum_theta_deg": "--maximum-theta-deg",
        "minimum_contrast": "--minimum-contrast",
        "minimum_fit_r2": "--minimum-fit-r2",
        "maximum_fit_nrmse": "--maximum-fit-nrmse",
        "maximum_reduced_chi2": "--maximum-reduced-chi2",
        "minimum_fit_p_value": "--minimum-fit-p-value",
        "maximum_width_error_nm": "--maximum-width-error-nm",
        "maximum_width_relative_error": "--maximum-width-relative-error",
        "maximum_width_nm": "--maximum-width-nm",
    }
    tokens: list[str] = []
    for field, option in names.items():
        value = getattr(cuts, field)
        if value is not None:
            tokens.extend((option, str(value)))
    return tokens
