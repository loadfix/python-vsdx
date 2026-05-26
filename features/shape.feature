Feature: Shape authoring — built-in autoshapes
  In order to compose Visio drawings programmatically
  As a vsdx developer
  I want ShapeTree.add_shape to instantiate the built-in masters
  with a sensible geometry / id / text surface

  Background:
    Given a fresh blank document with one page

  Scenario: Add a Rectangle by enum
     When I add a Rectangle at (2, 5) sized (2, 1)
     Then the shape's master_name_u is "Rectangle"
      And the shape's pin is (2.0, 5.0)
      And the shape's size is (2.0, 1.0)
      And the shape has a unique shape_id

  Scenario: Add an Ellipse by string
     When I add a shape with master_name "Ellipse" at (3, 4) sized (1.5, 1.5)
     Then the shape's master_name_u is "Ellipse"
      And the shape's pin is (3.0, 4.0)

  Scenario: Add a Triangle
     When I add a Triangle at (1, 1) sized (1, 1)
     Then the shape's master_name_u is "Triangle"

  Scenario: Set initial text in add_shape
     When I add a Rectangle at (2, 5) sized (2, 1) with text "Hello"
     Then the shape's text reads back as "Hello"

  Scenario: Mutate position and size
     When I add a Rectangle at (2, 5) sized (2, 1)
      And I move the shape to (4, 6) and resize to (3, 2)
     Then the shape's pin is (4.0, 6.0)
      And the shape's size is (3.0, 2.0)

  Scenario: Iterate page shapes
     When I add a Rectangle at (2, 5) sized (2, 1)
      And I add a Triangle at (5, 5) sized (1, 1)
     Then the page iterates two shapes

  Scenario: Index page shapes
     When I add a Rectangle at (2, 5) sized (2, 1)
      And I add an Ellipse at (5, 5) sized (1, 1)
     Then the first shape's master_name_u is "Rectangle"
      And the second shape's master_name_u is "Ellipse"

  Scenario: Round-trip a shaped document through a buffer
     When I add a Rectangle at (2, 5) sized (2, 1) with text "Round-trip"
      And I save the document and re-open from the buffer
     Then the re-opened first page has one shape
      And the re-opened first shape's text reads back as "Round-trip"
