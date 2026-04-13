from typing import Optional

from pydantic import BaseModel


class PerfumeEntity(BaseModel):
    name: str
    brand: Optional[str] = None
    category: Optional[str] = None


class PriceSnapshot(BaseModel):
    perfume_name: str
    price: Optional[float] = None
    currency: Optional[str] = None
    retailer: Optional[str] = None


class DiscountSnapshot(BaseModel):
    perfume_name: str
    discount_percent: Optional[float] = None
    retailer: Optional[str] = None
