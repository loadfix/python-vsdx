Feature: Connector authoring — glue / reroute / route style
  In order to wire shapes with dynamic connectors
  As a vsdx developer
  I want ShapeTree.add_connector to glue two shapes together,
  expose source / target, and reroute on demand

  Background:
    Given a fresh blank document with one page
    And two anchor shapes at (1, 1) and (5, 5)

  Scenario: add_connector returns a Connector
     When I connect the two shapes
     Then the connector is a vsdx.Connector
      And the connector has a unique shape_id

  Scenario: Connector source / target resolve
     When I connect the two shapes
     Then the connector source is the first anchor
      And the connector target is the second anchor

  Scenario: Connector inherits Dynamic Connector master
     When I connect the two shapes
     Then the connector master_name_u is "Dynamic connector"

  Scenario: Set route_style via VS_CONNECTOR_STYLE
     When I connect the two shapes
      And I set the route style to right-angle
     Then the connector route_style reads back as right-angle

  Scenario: Reroute connector pins
     When I connect the two shapes
      And I reroute the connector
     Then the connector begin and end coordinates are populated

  Scenario: Connections-out / connections-in resolve
     When I connect the two shapes
     Then the first anchor reports one outbound connection
      And the second anchor reports one inbound connection

  Scenario: Round-trip a connector through a buffer
     When I connect the two shapes
      And I save the document and re-open from the buffer
     Then the re-opened first page has three shapes
