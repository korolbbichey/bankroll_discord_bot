# Contributing to Bankroll

Thanks for wanting to help! Ideas and bug reports are welcome as GitHub issues, or in the bot itself with `/feedback`.

## Sending a pull request

1. Fork the repository and create a branch for your change.
2. Install the dependencies, including pytest: `pip install -r requirements-dev.txt`
3. Make your change. Keep the style of the code around it, and add or update tests in `tests/`.
4. If players will notice the change, add an entry at the top of `CHANGELOG` in `bot/changelog.py`, so players are told about it after the deploy.
5. Run the tests: `python -m pytest -q`. They must all pass.
6. Open a pull request and describe what changed and why.

Never commit a bot token or other secrets. The token lives only in `bot_key.env` (ignored by git) or in the hosting platform's environment variables.

## Terms for contributions

By sending a pull request or any other contribution to this repository, you agree that:

- the contribution is your own work, or you have the right to submit it;
- you grant the owner of this repository a perpetual, worldwide, irrevocable, royalty-free license to use, copy, change, distribute and sublicense your contribution, under the project's license or any other license, including commercially;
- your contribution is shared with everyone else under the project's license, the [PolyForm Noncommercial License 1.0.0](LICENSE.md).

You keep the copyright to your contribution.
