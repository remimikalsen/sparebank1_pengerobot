"""Utility functions for the Sparebank1 Pengerobot integration."""
import re
from decimal import Decimal, InvalidOperation

from .const import CURRENCY_RATES


def validate_norwegian_account_number(account_number: str) -> bool:
    """Validate Norwegian account number (11 digits)."""
    if not isinstance(account_number, str):
        return False
    
    # Remove any spaces or dots
    clean_number = re.sub(r'[\s\.]', '', account_number)
    
    # Check if it's exactly 11 digits
    if not re.match(r'^\d{11}$', clean_number):
        return False
    
    # Norwegian account numbers use modulo 11 checksum
    # Format: BBBBAAAAAAC (B=bank, A=account, C=checksum)
    weights = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    checksum = 0
    
    for i, digit in enumerate(clean_number[:10]):
        checksum += int(digit) * weights[i]
    
    remainder = checksum % 11
    expected_check_digit = 0 if remainder < 2 else 11 - remainder
    actual_check_digit = int(clean_number[10])
    
    return expected_check_digit == actual_check_digit


def validate_amount(amount_str: str, max_amount: float = None) -> tuple[bool, Decimal | None, str]:
    """
    Validate amount string and convert to Decimal.
    
    Returns:
        tuple: (is_valid, decimal_amount, error_message)
    """
    try:
        # Convert to Decimal for precision
        amount = Decimal(str(amount_str))
        
        # Check if positive
        if amount <= 0:
            return False, None, "Amount must be positive"
        
        # Check maximum amount if specified
        if max_amount is not None and amount > Decimal(str(max_amount)):
            return False, None, f"Amount cannot exceed {max_amount}"
        
        # Round to 2 decimal places for currency
        amount = amount.quantize(Decimal('0.01'))
        
        return True, amount, ""
        
    except (InvalidOperation, ValueError, TypeError):
        return False, None, "Invalid amount format"


def convert_currency(amount: Decimal, from_currency: str, to_currency: str) -> Decimal:
    """
    Convert amount from one currency to another using fixed exchange rates.
    
    Args:
        amount: Amount to convert
        from_currency: Source currency code
        to_currency: Target currency code
        
    Returns:
        Converted amount as Decimal
        
    Raises:
        ValueError: If currency is not supported
    """
    if from_currency not in CURRENCY_RATES:
        raise ValueError(f"Unsupported source currency: {from_currency}")
    if to_currency not in CURRENCY_RATES:
        raise ValueError(f"Unsupported target currency: {to_currency}")
    
    if from_currency == to_currency:
        return amount
    
    # Convert from source currency to NOK (base currency)
    nok_amount = amount / Decimal(str(CURRENCY_RATES[from_currency]))
    
    # Convert from NOK to target currency
    target_amount = nok_amount * Decimal(str(CURRENCY_RATES[to_currency]))
    
    # Round to 2 decimal places for currency precision
    return target_amount.quantize(Decimal('0.01'))


def validate_amount_with_currency_conversion(
    amount_str: str, 
    transfer_currency: str, 
    device_default_currency: str, 
    max_amount_in_default_currency: float
) -> tuple[bool, Decimal | None, str]:
    """
    Validate amount with currency conversion against device limits.
    
    Args:
        amount_str: Amount as string
        transfer_currency: Currency of the transfer
        device_default_currency: Default currency configured for the device
        max_amount_in_default_currency: Max amount limit in device default currency
        
    Returns:
        tuple: (is_valid, decimal_amount, error_message)
    """
    try:
        # First validate basic amount format
        is_valid, amount_decimal, error_msg = validate_amount(amount_str)
        if not is_valid:
            return is_valid, amount_decimal, error_msg
        
        # Convert transfer amount to device default currency for limit checking
        converted_amount = convert_currency(
            amount_decimal, 
            transfer_currency, 
            device_default_currency
        )
        
        # Check against max amount in device default currency
        if converted_amount > Decimal(str(max_amount_in_default_currency)):
            return False, None, (
                f"Transfer amount of {amount_decimal} {transfer_currency} "
                f"(equivalent to {converted_amount} {device_default_currency}) "
                f"exceeds maximum allowed amount of {max_amount_in_default_currency} {device_default_currency}"
            )
        
        return True, amount_decimal, ""
        
    except ValueError as e:
        return False, None, str(e)
    except (InvalidOperation, TypeError):
        return False, None, "Invalid amount or currency format"