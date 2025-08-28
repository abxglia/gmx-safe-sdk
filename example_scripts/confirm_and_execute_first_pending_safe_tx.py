import os
import json
import dotenv

dotenv.load_dotenv()

from gmx_python_sdk.scripts.v2.safe_utils import (
    list_safe_pending_transactions,
    execute_safe_transaction,
)


def main():
    safe_address = os.getenv('SAFE_ADDRESS') or os.getenv('GMX_SAFE_ADDRESS')
    safe_api_url = os.getenv('SAFE_API_URL')
    api_key = os.getenv('SAFE_TRANSACTION_SERVICE_API_KEY')
    rpc_url = os.getenv('RPC_URL') or os.getenv('ARBITRUM_RPC')
    private_key = os.getenv('PRIVATE_KEY')

    if not safe_address or not safe_api_url or not rpc_url or not private_key:
        print('Missing one of required envs: SAFE_ADDRESS, SAFE_API_URL, RPC_URL, PRIVATE_KEY')
        return

    pending = list_safe_pending_transactions(
        safe_address=safe_address,
        safe_api_url=safe_api_url,
        api_key=api_key,
        limit=1,
        offset=0,
    )
    print('List pending result:')
    print(json.dumps(pending, indent=2))

    if pending.get('status') != 'success' or pending.get('count', 0) == 0:
        print('No pending txs or failed to list')
        return

    first = pending['results'][0]
    safe_tx_hash = first['safeTxHash']

    # Execute the transaction directly (handles signing and execution)
    execute = execute_safe_transaction(
        safe_address=safe_address,
        safe_tx_hash=safe_tx_hash,
        rpc_url=rpc_url,
        private_key=private_key,
        safe_api_url=safe_api_url,
        api_key=api_key,
    )
    print('Execute result:')
    print(json.dumps(execute, indent=2))


if __name__ == '__main__':
    main()