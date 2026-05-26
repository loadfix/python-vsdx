Feature: Page collection — add, remove, iterate, geometry
  In order to author a multi-page Visio drawing
  As a vsdx developer
  I want Pages.add_page / remove / iteration and Page.width / .height
  to behave the same way as their docx / pptx siblings

  Background:
    Given a fresh blank document with one page

  Scenario: Default page geometry is letter-portrait
     When I read the page width and height
     Then the page width matches 8.5 inches
      And the page height matches 11.0 inches

  Scenario: Set a custom page name
     When I set the page name to "Architecture"
     Then the page name reads back as "Architecture"

  Scenario: Resize a page
     When I set the page width to 17.0 inches
      And I set the page height to 11.0 inches
     Then the page width matches 17.0 inches
      And the page height matches 11.0 inches

  Scenario: Add a second page and iterate
     When I add a second page
     Then the document iterates two pages
      And the document indexes the pages by 0 and 1

  Scenario: Remove a page
     When I add a second page
      And I remove the second page
     Then the document iterates one page

  Scenario: Add a background page
     When I add a background page
     Then the document has one foreground page
      And the document has one background page

  Scenario: Wire a foreground page to a background page
     When I add a background page
      And I assign the background page to the foreground page
     Then the foreground page reports its background_page

  Scenario: Iterate pages with for-loop
     When I add a second page
     Then iterating doc.pages yields two Page objects
