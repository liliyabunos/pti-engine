from perfume_trend_sdk.core.errors.base import PerfumeTrendSDKError


class NormalizationError(PerfumeTrendSDKError):
    pass


class ExtractionError(PerfumeTrendSDKError):
    pass


class ResolutionError(PerfumeTrendSDKError):
    pass


class EnrichmentError(PerfumeTrendSDKError):
    pass


class PublishError(PerfumeTrendSDKError):
    pass
