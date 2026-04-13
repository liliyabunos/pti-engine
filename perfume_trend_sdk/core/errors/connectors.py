from perfume_trend_sdk.core.errors.base import PerfumeTrendSDKError


class ConnectorHealthcheckError(PerfumeTrendSDKError):
    pass


class FetchError(PerfumeTrendSDKError):
    pass
