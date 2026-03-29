import logging

from web3 import Web3

from core.config import BotConfig

logger = logging.getLogger("polybot.wallet")

# USDC on Polygon
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
USDC_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "remaining", "type": "uint256"}],
        "type": "function",
    },
]


class WalletManager:
    def __init__(self, config: BotConfig):
        self.config = config
        self._w3: Web3 | None = None
        self._address: str = ""

    def connect(self):
        if not self.config.polygon_rpc_url:
            logger.warning("No POLYGON_RPC_URL configured — wallet manager disabled")
            return

        self._w3 = Web3(Web3.HTTPProvider(self.config.polygon_rpc_url))
        if self.config.private_key:
            acct = self._w3.eth.account.from_key(self.config.private_key)
            self._address = acct.address
            logger.info("Wallet connected: %s", self._address)
        elif self.config.funder_address:
            self._address = self.config.funder_address

    @property
    def address(self) -> str:
        return self._address

    def get_matic_balance(self) -> float:
        if not self._w3 or not self._address:
            return 0.0
        balance_wei = self._w3.eth.get_balance(self._address)
        return float(self._w3.from_wei(balance_wei, "ether"))

    def get_usdc_balance(self) -> float:
        if not self._w3 or not self._address:
            return 0.0
        contract = self._w3.eth.contract(
            address=Web3.to_checksum_address(USDC_ADDRESS),
            abi=USDC_ABI,
        )
        raw = contract.functions.balanceOf(
            Web3.to_checksum_address(self._address)
        ).call()
        return raw / 1e6  # USDC has 6 decimals

    def check_balances(self) -> dict:
        matic = self.get_matic_balance()
        usdc = self.get_usdc_balance()
        logger.info("Balances — MATIC: %.4f, USDC: %.2f", matic, usdc)
        return {"matic": matic, "usdc": usdc}
