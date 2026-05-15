"""Service-layer modules for v1.

Each service is a stateless module with a single public function. Composed
in `app.routers.plan` to form the v1 pipeline:

    geocoder → stay_defaults → chain → directions → response_builder

Will be filled in across days 3-8. Empty for now.
"""
