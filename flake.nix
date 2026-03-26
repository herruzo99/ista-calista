{
  description = "A development environment for the Ista Calista Home Assistant component.";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };

        # Reference the home-assistant derivation from nixpkgs. This is our foundation.
        ha = pkgs.home-assistant;

        # Build pycalista-ista from GitHub to provide all required dependencies.
        # The shellHook below prepends the local sibling directory to PYTHONPATH so
        # that the 0.8.0 development version takes precedence at runtime.
        pycalista-ista-for-ha = ha.python.pkgs.buildPythonPackage rec {
          pname = "pycalista-ista";
          version = "0.9.2";
          format = "pyproject";

          src = pkgs.fetchFromGitHub {
            owner = "herruzo99";
            repo = "pycalista-ista";
            rev = "v${version}";
            hash = "sha256-I7dLItJ0N9jFnnxRwPljvLYUqB8on1x7DprqT3Sg4JY=";
          };

          # All dependencies are now drawn from `ha.python.pkgs`, ensuring consistency.
          propagatedBuildInputs = with ha.python.pkgs; [
            setuptools
            aiohttp
            beautifulsoup4
            lxml
            requests
            pandas
            xlrd
            openpyxl
            unidecode
          ];

          pythonImportsCheck = [ "pycalista_ista" ];
        };

        # Build the final test environment using the exact Python provided by the
        # home-assistant derivation.
        pythonTestEnv = ha.python.withPackages (ps: with ps; [
          # Test dependencies, all sourced from the consistent HA package set.
          pytest
          pytest-cov
          pytest-homeassistant-custom-component
          aioresponses
          freezegun
          ruff
          isort
          black
          mypy

          # Add our consistently-built package to the environment.
          pycalista-ista-for-ha
        ]);

      in
      {
        # The primary development shell.
        devShells.default = pkgs.mkShell {
          name = "ista-calista-dev";

          packages = [
            pythonTestEnv
            pkgs.pre-commit
          ];

          shellHook = ''
            # Override pycalista-ista with the local 0.8.0 development version.
            # This sibling directory takes precedence over the nix-built 0.7.0.
            PYCALISTA_LOCAL="$(readlink -f "$PWD/../pycalista-ista")"
            if [ -d "$PYCALISTA_LOCAL" ]; then
              export PYTHONPATH="$PYCALISTA_LOCAL:$PYTHONPATH"
            fi

            # Add the project's custom_components directory to the PYTHONPATH.
            # This is crucial for pytest to discover the integration's code.
            export PYTHONPATH="$PWD/custom_components:$PYTHONPATH"

            if [ -f .pre-commit-config.yaml ]; then
              pre-commit install -f --install-hooks
            fi

            echo ""
            echo "----------------------------------------------------------"
            echo "  Nix dev shell for ista_calista is activated."
            echo ""
            echo "  To run tests, execute: pytest"
            echo "----------------------------------------------------------"
            echo ""
          '';
        };
      });
}
