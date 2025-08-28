import os
import json

from gmx_python_sdk.scripts.v2.safe_utils import list_safe_pending_transactions

import dotenv
dotenv.load_dotenv()

def main():
    safe_address = os.getenv('SAFE_ADDRESS') or os.getenv('GMX_SAFE_ADDRESS')
    safe_api_url = os.getenv('SAFE_API_URL')
    api_key = os.getenv('SAFE_TRANSACTION_SERVICE_API_KEY')

    if not safe_address or not safe_api_url:
        print("SAFE_ADDRESS and SAFE_API_URL env vars are required")
        return

    result = list_safe_pending_transactions(
        safe_address=safe_address,
        safe_api_url=safe_api_url,
        api_key=api_key,
        limit=100,
        offset=0,
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()


