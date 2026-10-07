"""
Zero-Cost Fax Gateway - Retry Utility
Implements exponential backoff with full jitter for resilient network operations.
"""

import asyncio
import functools
import random
import time
from typing import Any, Callable, Tuple, Type


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 2.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    retry_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    logger: Any = None,
):
    """
    Decorator for synchronous functions to retry with exponential backoff.
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None

            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retry_exceptions as e:
                    last_exception = e
                    if attempt == max_retries:
                        if logger:
                            logger.error(
                                f"Operation '{func.__name__}' failed after {max_retries} attempts: {e}"
                            )
                        raise

                    actual_delay = delay
                    if jitter:
                        actual_delay = random.uniform(0.5 * delay, 1.5 * delay)

                    if logger:
                        logger.warning(
                            f"Attempt {attempt}/{max_retries} failed for '{func.__name__}': {e}. "
                            f"Retrying in {actual_delay:.1f}s..."
                        )

                    time.sleep(actual_delay)
                    delay *= backoff_factor

            if last_exception:
                raise last_exception

        return wrapper
    return decorator


def async_retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 2.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    retry_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    logger: Any = None,
):
    """
    Decorator for asynchronous coroutines to retry with exponential backoff.
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None

            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except retry_exceptions as e:
                    last_exception = e
                    if attempt == max_retries:
                        if logger:
                            logger.error(
                                f"Async operation '{func.__name__}' failed after {max_retries} attempts: {e}"
                            )
                        raise

                    actual_delay = delay
                    if jitter:
                        actual_delay = random.uniform(0.5 * delay, 1.5 * delay)

                    if logger:
                        logger.warning(
                            f"Attempt {attempt}/{max_retries} failed for '{func.__name__}': {e}. "
                            f"Retrying in {actual_delay:.1f}s..."
                        )

                    await asyncio.sleep(actual_delay)
                    delay *= backoff_factor

            if last_exception:
                raise last_exception

        return wrapper
    return decorator
