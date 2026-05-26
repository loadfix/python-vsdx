Feature: Master catalog — built-in masters
  In order for shapes to reference reusable templates
  As a vsdx developer
  I want Masters.add_master / .ensure / .resolve and Masters lookups
  to manage the master catalog correctly

  Scenario: Empty document has no masters
    Given a fresh blank document with one page
    Then the document has zero masters

  Scenario: add_master appends a master
    Given a fresh blank document with one page
    When I add the Rectangle master
    Then the document has one master
     And the master's name_u is "Rectangle"
     And the master_id is "1"

  Scenario: ensure is idempotent
    Given a fresh blank document with one page
    When I ensure the Triangle master
     And I ensure the Triangle master again
    Then the document has one master
     And iterating masters yields one Master

  Scenario: __contains__ accepts a name string
    Given a fresh blank document with one page
    When I add the Ellipse master
    Then the document masters contain "Ellipse"
     And the document masters do not contain "Rectangle"

  Scenario: __getitem__ resolves by name
    Given a fresh blank document with one page
    When I add the Triangle master
    Then doc.masters['Triangle'] returns a Master with name_u "Triangle"

  Scenario: resolve(None) returns None
    Given a fresh blank document with one page
    Then doc.masters.resolve(None) returns None

  Scenario: Round-trip a master through a buffer
    Given a fresh blank document with one page
    When I add the Rectangle master
     And I save the document and re-open from the buffer
    Then the re-opened document has one master
     And the re-opened master's name_u is "Rectangle"
